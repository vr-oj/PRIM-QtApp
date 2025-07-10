import os
import logging

# Ensure bundled Thorlabs DLLs are discoverable when running the app
dll_path = os.path.join(os.path.dirname(__file__), "..", "dlls", "ThorLabs")
os.add_dll_directory(dll_path)
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

try:
    from thorlabs_tsi_sdk.tl_camera import TLCameraSDK
    THORLABS_AVAILABLE = True
except Exception as e:
    TLCameraSDK = None
    THORLABS_AVAILABLE = False
    logging.getLogger(__name__).error(f"Thorlabs SDK not available: {e}")

log = logging.getLogger(__name__)


class ThorlabsCameraThread(QThread):
    """Acquire frames from a Thorlabs camera using the thorlabs_tsi_sdk."""

    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str)

    def __init__(self, parent=None, dll_path=None):
        super().__init__(parent)
        self._stop_requested = False
        self.dll_path = dll_path
        self.sdk = None
        self.camera = None

    def _init_sdk(self):
        if not THORLABS_AVAILABLE:
            raise RuntimeError("thorlabs_tsi_sdk not installed")
        if self.dll_path:
            try:
                os.add_dll_directory(self.dll_path)
            except Exception as e:
                log.warning(f"Failed to add DLL directory '{self.dll_path}': {e}")
        self.sdk = TLCameraSDK()

    def run(self):
        try:
            self._init_sdk()
            cams = self.sdk.discover_available_cameras()
            if not cams:
                raise RuntimeError("No Thorlabs cameras found")
            self.camera = self.sdk.open_camera(cams[0])
            self.camera.exposure_time_us = 10000
            self.camera.frames_per_trigger_zero_for_unlimited = 0
            self.camera.arm(2)
            self.camera.issue_software_trigger()

            while not self._stop_requested:
                frame = self.camera.get_pending_frame_or_null()
                if frame:
                    image = frame.image_buffer.copy()
                    self.camera.dispose_frame(frame)
                    if image.dtype != np.uint8:
                        max_val = float(image.max()) if image.max() > 0 else 1.0
                        image = (image / max_val * 255.0).astype(np.uint8)
                    h, w = image.shape
                    qimg = QImage(image.data, w, h, image.strides[0], QImage.Format_Grayscale8).copy()
                    self.frame_ready.emit(qimg, image)
                else:
                    self.msleep(1)
        except Exception as e:
            log.error(f"ThorlabsCameraThread error: {e}")
            self.error.emit(str(e))
        finally:
            self.shutdown()

    def stop(self):
        self._stop_requested = True
        self.wait()

    def shutdown(self):
        if self.camera:
            try:
                self.camera.disarm()
            except Exception:
                pass
            try:
                self.camera.dispose()
            except Exception:
                pass
            self.camera = None
        if self.sdk:
            try:
                self.sdk.dispose()
            except Exception:
                pass
            self.sdk = None
