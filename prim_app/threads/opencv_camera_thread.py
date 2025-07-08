import logging
import cv2
import numpy as np

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class OpenCVCameraThread(QThread):
    """Simple QThread that reads frames from an OpenCV VideoCapture."""

    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str)

    def __init__(self, index=0, parent=None):
        super().__init__(parent)
        self.index = index
        self.cap = None
        self._stop_requested = False

    def _cv_to_qimage(self, frame: np.ndarray) -> QImage:
        """Convert an OpenCV frame to QImage."""
        if frame.ndim == 2:
            h, w = frame.shape
            bytes_per_line = frame.strides[0]
            return QImage(frame.data, w, h, bytes_per_line, QImage.Format_Grayscale8).copy()

        h, w, ch = frame.shape
        if ch == 3:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            bytes_per_line = rgb.strides[0]
            return QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888).copy()
        elif ch == 4:
            rgba = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGBA)
            bytes_per_line = rgba.strides[0]
            return QImage(rgba.data, w, h, bytes_per_line, QImage.Format_RGBA8888).copy()

        raise ValueError("Unsupported frame format")

    def run(self):
        try:
            self.cap = cv2.VideoCapture(self.index)
            if not self.cap.isOpened():
                raise RuntimeError(f"Failed to open camera index {self.index}")

            while not self._stop_requested:
                ret, frame = self.cap.read()
                if not ret:
                    self.msleep(10)
                    continue
                try:
                    qimg = self._cv_to_qimage(frame)
                except Exception:
                    log.exception("Failed to convert frame to QImage")
                    self.msleep(1)
                    continue
                self.frame_ready.emit(qimg, frame)
                self.msleep(1)
        except Exception as e:
            log.error(f"OpenCVCameraThread error: {e}")
            self.error.emit(str(e))
        finally:
            if self.cap is not None:
                self.cap.release()
                self.cap = None

    def stop(self):
        self._stop_requested = True
