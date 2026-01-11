import asyncio
import json
import threading
import numpy as np
import struct
from aiohttp import web
import ssl
import os
import time

# ----------------------------------------------------------------------------
# 1. The HTML Client (Runs on Quest 3)
# ----------------------------------------------------------------------------
HTML_CLIENT = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { background-color: #333; color: white; font-family: monospace; text-align: center; margin-top: 50px; }
        button { font-size: 20px; padding: 15px 30px; cursor: pointer; }
        #status { margin-top: 20px; font-size: 18px; color: #8f8; }
        #log { font-size: 12px; color: #ccc; margin-top: 10px; white-space: pre-wrap; text-align: left; padding: 10px; border-top: 1px solid #555;}
    </style>
</head>
<body>
    <h1>Mac WebXR Bridge (Binary v9 - AR)</h1>
    <p>Please REFRESH this page if you don't see (v9)</p>
    <button onclick="activateXR()">ENTER AR/VR</button>
    <div id="status">Waiting...</div>
    <div id="log"></div>
    <canvas id="xr-canvas" style="display:none;"></canvas>

<script>
let protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
let ws = new WebSocket(protocol + window.location.host + '/ws');
ws.binaryType = "arraybuffer"; 

let xrSession = null;
let xrRefSpace = null;
let gl = null;
let sendBuffer = new Float32Array(27); 

function remoteLog(msg) {
    if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({type: 'log', msg: msg}));
    }
    console.log(msg);
    let d = new Date();
    document.getElementById('log').innerText = "[" + d.toLocaleTimeString() + "] " + msg + "\\n" + document.getElementById('log').innerText.substring(0, 500);
}

ws.onopen = () => { document.getElementById('status').innerText = "Connected (Binary Mode)"; };

async function activateXR() {
  if (!navigator.xr) { remoteLog("WebXR not found"); return; }
  try {
    // CHECK FOR AR (Pass-through) SUPPORT
    const arSupported = await navigator.xr.isSessionSupported('immersive-ar');
    const mode = arSupported ? 'immersive-ar' : 'immersive-vr';
    
    if (!arSupported) {
        const vrSupported = await navigator.xr.isSessionSupported('immersive-vr');
        if (!vrSupported) { remoteLog("XR NOT supported."); return; }
    }

    let canvas = document.getElementById('xr-canvas');
    gl = canvas.getContext('webgl', { xrCompatible: true });

    // Request AR if possible, otherwise VR
    xrSession = await navigator.xr.requestSession(mode, { requiredFeatures: ['local-floor'] });
    xrSession.updateRenderState({ baseLayer: new XRWebGLLayer(xrSession, gl) });
    
    // IMPORTANT: Clear to TRANSPARENT for Passthrough
    gl.clearColor(0.0, 0.0, 0.0, 0.0);
    
    xrSession.addEventListener('end', () => remoteLog("Session ENDED"));
    
    try { xrRefSpace = await xrSession.requestReferenceSpace('local-floor'); } 
    catch (e) { xrRefSpace = await xrSession.requestReferenceSpace('viewer'); }

    remoteLog("Starting Binary Loop (" + mode + ")...");
    xrSession.requestAnimationFrame(onXRFrame);
  } catch(e) { remoteLog("Error: " + e); }
}

function onXRFrame(time, frame) {
  let session = frame.session;
  // Clear Active flags
  sendBuffer[7] = 0.0; 
  sendBuffer[17] = 0.0; 

  let glLayer = session.renderState.baseLayer;
  gl.bindFramebuffer(gl.FRAMEBUFFER, glLayer.framebuffer);
  
  // Clear buffer to transparent (reveals real world in AR mode)
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

  let pose = frame.getViewerPose(xrRefSpace);
  if (pose && ws.readyState === WebSocket.OPEN) {
    // Head
    sendBuffer[0] = pose.transform.position.x;
    sendBuffer[1] = pose.transform.position.y;
    sendBuffer[2] = pose.transform.position.z;
    sendBuffer[3] = pose.transform.orientation.x;
    sendBuffer[4] = pose.transform.orientation.y;
    sendBuffer[5] = pose.transform.orientation.z;
    sendBuffer[6] = pose.transform.orientation.w;

    for (let source of session.inputSources) {
        if (!source.gripSpace) continue;
        let offset = (source.handedness === 'left') ? 7 : 17;
        
        // Mark Active
        sendBuffer[offset] = 1.0; 

        let gripPose = frame.getPose(source.gripSpace, xrRefSpace);
        if (gripPose) {
            sendBuffer[offset+1] = gripPose.transform.position.x;
            sendBuffer[offset+2] = gripPose.transform.position.y;
            sendBuffer[offset+3] = gripPose.transform.position.z;
            sendBuffer[offset+4] = gripPose.transform.orientation.x;
            sendBuffer[offset+5] = gripPose.transform.orientation.y;
            sendBuffer[offset+6] = gripPose.transform.orientation.z;
            sendBuffer[offset+7] = gripPose.transform.orientation.w;
        }

        if (source.gamepad) {
            sendBuffer[offset+8] = source.gamepad.buttons[0]?.value || 0; // Trigger
            sendBuffer[offset+9] = source.gamepad.buttons[1]?.value || 0; // Grip
        }
    }
    ws.send(sendBuffer);
  }
  session.requestAnimationFrame(onXRFrame);
}
</script>
</body>
</html>
"""


class MockVector3f:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = x, y, z

    def as_numpy(self): return np.array([self.x, self.y, self.z])


class MockQuaternionf:
    def __init__(self, x=0.0, y=0.0, z=0.0, w=1.0):
        self.x, self.y, self.z, self.w = x, y, z, w


class MockController:
    def __init__(self, name):
        self.name = name
        self.position = MockVector3f()
        self.orientation = MockQuaternionf()
        self.grip_button = False
        self.trigger = 0.0

    def update_raw(self, pos, rot, trigger, grip):
        # Only update pos/rot if they are not all zero (simple check)
        if not (pos[0] == 0 and pos[1] == 0 and pos[2] == 0):
            self.position.x, self.position.y, self.position.z = pos
            self.orientation.x, self.orientation.y, self.orientation.z, self.orientation.w = rot

        self.trigger = trigger
        self.grip_button = grip > 0.5


class WebXrBridge:
    def __init__(self, port=8080):
        self._hmd_position = MockVector3f()
        self._hmd_orientation = MockQuaternionf()
        self.left_controller = MockController("Left")
        self.right_controller = MockController("Right")
        self.controllers = [self.left_controller, self.right_controller]

        self.port = port
        self.packet_count = 0
        self.server_thread = threading.Thread(target=self._run_server_loop, daemon=True)
        self.server_thread.start()
        print(f"\n[WebXR Binary Bridge] Running on https://<IP>:{port}\n")

    def _run_server_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        app = web.Application()
        app.add_routes([
            web.get('/', self._handle_index),
            web.get('/ws', self._handle_websocket)
        ])

        ssl_context = None
        if os.path.exists("cert.pem") and os.path.exists("key.pem"):
            ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain('cert.pem', 'key.pem')

        runner = web.AppRunner(app)
        loop.run_until_complete(runner.setup())
        site = web.TCPSite(runner, '0.0.0.0', self.port, ssl_context=ssl_context)
        loop.run_until_complete(site.start())
        loop.run_forever()

    async def _handle_index(self, request):
        return web.Response(text=HTML_CLIENT, content_type='text/html')

    async def _handle_websocket(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        print(">>> HEADSET CONNECTED <<<")

        async for msg in ws:
            if msg.type == web.WSMsgType.BINARY:
                try:
                    if len(msg.data) >= 108:
                        self.packet_count += 1
                        floats = struct.unpack('27f', msg.data[:108])

                        # Debug Heartbeat every ~60 frames
                        if self.packet_count % 60 == 0:
                            print(f"[Bridge] Heartbeat: {self.packet_count} packets. HeadX: {floats[0]:.2f}")

                        # Update Left (Offset 7)
                        if floats[7] > 0.5:
                            self.left_controller.update_raw(
                                pos=floats[8:11],
                                rot=floats[11:15],
                                trigger=floats[15],
                                grip=floats[16]
                            )

                        # Update Right (Offset 17)
                        if floats[17] > 0.5:
                            self.right_controller.update_raw(
                                pos=floats[18:21],
                                rot=floats[21:25],
                                trigger=floats[25],
                                grip=floats[26]
                            )
                except Exception as e:
                    print(f"Packet Error: {e}")

            elif msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    if data.get('type') == 'log':
                        print(f"[QUEST LOG] {data.get('msg')}")
                except:
                    pass

        print(">>> HEADSET DISCONNECTED <<<")
        return ws

    def update(self):
        pass

    def exit(self):
        pass

# 192.168.1.129:8080
