import logging
import importlib
import numpy as np

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class AndorCameraThread(QThread):
    """Acquire frames from an Andor SDK3 camera."""

    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_requested = False
        self.camera = None
        try:
            self.andor = importlib.import_module("andor3")
            self.available = True
        except ImportError as e:
            log.error(f"Andor SDK3 not found: {e}")
            self.andor = None
            self.available = False

    def run(self):
        if not self.available:
            self.error.emit("Andor SDK3 not available")
            return
        try:
            self.camera = self.andor.AndorCamera()
            self.camera.open()
            self.camera.start_acquisition()
            while not self._stop_requested:
                if self.camera.image_ready():
                    frame = self.camera.get_latest_image()
                    arr = np.asarray(frame)
                    if arr.ndim == 2:
                        fmt = QImage.Format_Grayscale8
                    else:
                        fmt = QImage.Format_RGB888
                        arr = arr[:, :, :3]
                    h, w = arr.shape[:2]
                    qimg = QImage(arr.data, w, h, arr.strides[0], fmt).copy()
                    self.frame_ready.emit(qimg, arr)
                else:
                    self.msleep(1)
            self.camera.stop_acquisition()
            self.camera.close()
        except Exception as e:
            log.error(f"AndorCameraThread error: {e}")
            self.error.emit(str(e))
        finally:
            if self.camera:
                try:
                    self.camera.close()
                except Exception:
                    pass
                self.camera = None

    def stop(self):
        self._stop_requested = True
