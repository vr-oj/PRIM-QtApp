# Camera backend using mmcoreplus for Micro-Manager devices

import os
from typing import Optional

from .base import CameraBase

try:
    from pymmcore_plus import CMMCorePlus
except Exception:  # Module may not be installed in dev environment
    CMMCorePlus = None  # type: ignore


def find_micromanager_path(start_dir: Optional[str] = None) -> Optional[str]:
    """Return the path to bundled Micro-Manager directory if found."""
    if start_dir is None:
        start_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mm_path = os.path.join(start_dir, "micromanager")
    return mm_path if os.path.isdir(mm_path) else None


class MicroManagerCamera(CameraBase):
    """Simple mmcoreplus based camera backend."""

    def __init__(self, config_file: str, mm_path: Optional[str] = None):
        self.config_file = config_file
        self.mm_path = mm_path or find_micromanager_path()
        self.core: Optional[CMMCorePlus] = None

    def connect(self):
        if CMMCorePlus is None:
            raise RuntimeError("pymmcore-plus not installed")
        if not self.mm_path:
            raise RuntimeError("Micro-Manager path not found")
        self.core = CMMCorePlus(adapter_paths=[self.mm_path])
        if self.config_file:
            self.core.loadSystemConfiguration(self.config_file)
        self.core.initializeAllDevices()

    def disconnect(self):
        if self.core:
            try:
                self.core.reset()
            finally:
                self.core = None

    def start_stream(self):
        if self.core:
            self.core.startContinuousSequenceAcquisition(0)

    def stop_stream(self):
        if self.core and self.core.is_sequence_running():
            self.core.stopSequenceAcquisition()

    def get_frame(self):
        if not self.core:
            return None
        if self.core.getRemainingImageCount() > 0:
            return self.core.popNextImage()
        return None

    def set_property(self, prop_name: str, value):
        if self.core:
            self.core.setProperty(prop_name, value)
