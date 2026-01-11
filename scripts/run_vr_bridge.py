import platform
import time
import sys
import numpy as np
from scipy.spatial.transform import Rotation
from cc.udp import UDP

# Visualization Imports
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
import pyqtgraph.opengl as gl

if __name__ == "__main__":
    # 1. Setup Bridge
    if platform.system() == "Darwin":
        from steamvr_bridge.webxr_bridge import WebXrBridge
        bridge = WebXrBridge()
        print("Using WebXR Bridge on macOS")
    else:
        from steamvr_bridge.steamvr_bridge import SteamVrBridge
        bridge = SteamVrBridge()
        print("Using SteamVR Bridge on non-macOS")

    # 2. Setup Network
    udp = UDP(recv_addr=("0.0.0.0", 11005), send_addr=("192.168.1.230", 11005))

    controller_states = {
        "left": {"pose": [], "button_pressed": False, "trigger": 0},
        "right": {"pose": [], "button_pressed": False, "trigger": 0}
    }

    # 3. Setup Visualization Window
    app = QApplication(sys.argv)
    w = gl.GLViewWidget()
    w.opts['distance'] = 2.0  # Initial camera distance
    w.setWindowTitle('VR Bridge Controller Visualizer')
    w.setGeometry(0, 50, 800, 600)
    w.show()

    # Add Floor Grid
    grid = gl.GLGridItem()
    grid.setSize(x=5, y=5, z=5)
    grid.setSpacing(x=0.5, y=0.5, z=0.5)
    w.addItem(grid)

    # Add Controller Axes (Red=X, Green=Y, Blue=Z)
    left_axis = gl.GLAxisItem()
    left_axis.setSize(0.1, 0.1, 0.1)  # 10cm size
    w.addItem(left_axis)

    right_axis = gl.GLAxisItem()
    right_axis.setSize(0.1, 0.1, 0.1)
    w.addItem(right_axis)

    # 4. Update Loop (Replaces while True)
    def update():
        bridge.update()

        # UPDATED TRANSFORMATION
        # Assuming Sim Env is Z-Up (Grid on XY plane)
        # X_sim = -Y_real (Real Up -> Sim Left)
        # Y_sim = -X_real (Real Right -> Sim Front)
        # Z_sim =  Z_real (Real Back -> Sim Up)
        T_fix = np.array([
            [0,  0,  -1,  0],
            [-1,  0,  0,  0],
            [0, 1,  0,  0],
            [0,  0,  0,  1]
        ])

        # --- LEFT CONTROLLER ---
        # 1. Construct Raw Matrix (Real World)
        left_raw = np.eye(4)
        left_raw[:3, :3] = Rotation.from_quat(np.array([
            bridge.left_controller.orientation.x,
            bridge.left_controller.orientation.y,
            bridge.left_controller.orientation.z,
            bridge.left_controller.orientation.w,
        ])).as_matrix()
        left_raw[:3, 3] = bridge.left_controller.position.as_numpy()

        # 2. Apply Transform
        left_final = T_fix @ left_raw

        # --- RIGHT CONTROLLER ---
        # 1. Construct Raw Matrix (Real World)
        right_raw = np.eye(4)
        right_raw[:3, :3] = Rotation.from_quat(np.array([
            bridge.right_controller.orientation.x,
            bridge.right_controller.orientation.y,
            bridge.right_controller.orientation.z,
            bridge.right_controller.orientation.w,
        ])).as_matrix()
        right_raw[:3, 3] = bridge.right_controller.position.as_numpy()

        # 2. Apply Transform
        right_final = T_fix @ right_raw

        # Update Python State & UDP (Send final mapped matrix)
        controller_states["left"]["pose"] = left_final.tolist()
        controller_states["right"]["pose"] = right_final.tolist()

        controller_states["left"]["button_pressed"] = bridge.left_controller.grip_button or (
            bridge.left_controller.trigger > 0.8)
        controller_states["right"]["button_pressed"] = bridge.right_controller.grip_button or (
            bridge.right_controller.trigger > 0.8)
        controller_states["left"]["trigger"] = bridge.left_controller.trigger
        controller_states["right"]["trigger"] = bridge.right_controller.trigger

        udp.send_dict(controller_states)

        # Update Visuals (Now showing Sim Frame)
        left_axis.setTransform(left_final)
        right_axis.setTransform(right_final)

        # Print debug occasionally
        # print(f"{time.time():.2f}", controller_states["left"]["trigger"])
        # print(bridge.left_controller.position.as_numpy(), bridge.right_controller.position.as_numpy())
        # print(left_rot_matrix, right_rot_matrix)

    # Run update at approx 60Hz (16ms)
    timer = QTimer()
    timer.timeout.connect(update)
    timer.start(10)

    # Start Event Loop
    sys.exit(app.exec_())
