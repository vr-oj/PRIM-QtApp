from typing import Optional
import numpy as np
from cameras.opencv_camera import OpenCVCamera
from .camera_plugin_interface import CameraPluginInterface


class OpenCVPlugin(CameraPluginInterface):
    """Plugin that wraps :class:`OpenCVCamera`."""

    def __init__(self, index: int = 0):
        self.index = index
        self._cam: Optional[OpenCVCamera] = None

    def initialize(self) -> None:
        self._cam = OpenCVCamera(self.index)
        self._cam.connect()

    def start_acquisition(self) -> None:
        if self._cam:
            self._cam.start_stream()

    def stop_acquisition(self) -> None:
        if self._cam:
            self._cam.stop_stream()

    def get_frame(self) -> Optional[np.ndarray]:
        if not self._cam:
            return None
        frame = self._cam.get_frame()
        return frame.copy() if frame is not None else None

    def set_exposure(self, value: float) -> None:
        if self._cam:
            self._cam.set_property("EXPOSURE", value)

    def close(self) -> None:
        if self._cam:
            self._cam.disconnect()
            self._cam = None
