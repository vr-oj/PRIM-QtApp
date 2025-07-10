from typing import Optional
from cameras.micromanager_camera import MicroManagerCamera
from .camera_plugin_interface import CameraPluginInterface


class MicroManagerPlugin(CameraPluginInterface):
    """Plugin that wraps :class:`MicroManagerCamera`."""

    def __init__(self, config_file: str, mm_path: Optional[str] = None):
        self.config_file = config_file
        self.mm_path = mm_path
        self._cam: Optional[MicroManagerCamera] = None

    def initialize(self) -> None:
        self._cam = MicroManagerCamera(self.config_file, self.mm_path)
        self._cam.connect()

    def start_acquisition(self) -> None:
        if self._cam:
            self._cam.start_stream()

    def stop_acquisition(self) -> None:
        if self._cam:
            self._cam.stop_stream()

    def get_frame(self):
        if not self._cam:
            return None
        frame = self._cam.get_frame()
        return frame.copy() if frame is not None else None

    def set_exposure(self, value: float) -> None:
        if self._cam and self._cam.core:
            self._cam.core.setExposure(value)

    def close(self) -> None:
        if self._cam:
            self._cam.disconnect()
            self._cam = None
