from .ic4_camera import IC4CameraController
from threads.sdk_camera_thread import SDKCameraThread


def create_camera_controller(name: str, *args, **kwargs):
    """Return a camera controller implementation by name."""
    name = name.lower()
    if name == "ic4":
        thread = SDKCameraThread(*args, **kwargs)
        return IC4CameraController(thread)
    raise ValueError(f"Unknown camera controller: {name}")
