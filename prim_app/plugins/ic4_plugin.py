from typing import Optional
import numpy as np
from cameras.ic4_camera import IC4Camera
from .camera_plugin_interface import CameraPluginInterface


class IC4Plugin(CameraPluginInterface):
    """Camera plugin that wraps :class:`IC4Camera`."""

    def __init__(self, device_info=None):
        self._device_info = device_info
        self._cam: Optional[IC4Camera] = None

    def initialize(self) -> None:
        self._cam = IC4Camera(self._device_info)
        self._cam.connect()
        self._cam.start_stream()

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
            self._cam.set_property("ExposureTime", value)

    def close(self) -> None:
        if self._cam:
            self._cam.disconnect()
            self._cam = None
