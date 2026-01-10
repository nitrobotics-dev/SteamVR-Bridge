import platform

# Only import the standard bridge logic if NOT on macOS.
# On macOS, importing 'xr' (pyopenxr) raises NotImplementedError.
if platform.system() != "Darwin":
    from .steamvr_bridge import SteamVrBridge
    from .quest3_controller import Quest3Controller
