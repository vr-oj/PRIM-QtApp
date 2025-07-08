import logging
import cv2
import numpy as np

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class OpenCVCameraThread(QThread):
    """Simple QThread that reads frames from an OpenCV VideoCapture."""

    frame_ready = pyqtSignal(QImage)
    error = pyqtSignal(str)

    def __init__(self, index=0, parent=None):
        super().__init__(parent)
        self.index = index
        self.cap = None
        self._stop_requested = False

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
                if frame.ndim == 3:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                else:
                    gray = frame
                h, w = gray.shape[:2]
                qimg = QImage(gray.data, w, h, gray.strides[0], QImage.Format_Grayscale8)
                self.frame_ready.emit(qimg)
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
