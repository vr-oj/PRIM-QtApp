from .serial_thread import SerialThread

# SDKCameraThread requires the external imagingcontrol4 package which may not be
# available on all platforms (e.g. macOS). Try to import it but fall back to a
# stub that raises a helpful error at instantiation time if the dependency is
# missing.
try:  # pragma: no cover - best effort import
    from .sdk_camera_thread import SDKCameraThread
except Exception:  # pragma: no cover
    class SDKCameraThread:  # type: ignore[misc]
        def __init__(self, *_, **__):
            raise RuntimeError(
                "imagingcontrol4 SDK is not available; SDKCameraThread cannot be used"
            )

# MicroManagerCameraThread similarly depends on optional imaging libraries.
try:  # pragma: no cover - best effort import
    from .micromanager_camera_thread import MicroManagerCameraThread
except Exception:  # pragma: no cover
    class MicroManagerCameraThread:  # type: ignore[misc]
        def __init__(self, *_, **__):
            raise RuntimeError(
                "MicroManager camera support is unavailable on this platform"
            )

__all__ = ["SerialThread", "SDKCameraThread", "MicroManagerCameraThread"]
