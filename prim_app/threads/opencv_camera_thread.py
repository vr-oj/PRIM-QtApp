# File: prim_app/threads/opencv_camera_thread.py
import logging
import cv2
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class OpenCVCameraThread(QThread):
    """Capture frames from an OpenCV VideoCapture device."""

    grabber_ready = pyqtSignal()  # for API compatibility (unused)
    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str, str)  # message, code

    def __init__(self, index=0, parent=None):
        super().__init__(parent)
        self.index = index
        self.cap = None
        self._stop_requested = False

    def run(self):
        try:
            self.cap = cv2.VideoCapture(self.index)
            if not self.cap.isOpened():
                self.error.emit(f"Unable to open camera {self.index}", "")
                return
            # Notify that camera is ready
            self.grabber_ready.emit()

            while not self._stop_requested:
                ret, frame = self.cap.read()
                if not ret or frame is None:
                    self.error.emit("Failed to read frame", "")
                    break
                h, w = frame.shape[:2]
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                qimg = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format_RGB888)
                self.frame_ready.emit(qimg, frame)
                self.msleep(1)
        except Exception as e:
            log.exception("OpenCVCameraThread encountered an error")
            self.error.emit(str(e), "")
        finally:
            if self.cap:
                self.cap.release()
                self.cap = None

    def stop(self):
        self._stop_requested = True
