# File: prim_app/threads/opencv_camera_thread.py

import logging
import cv2
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class OpenCVCameraThread(QThread):
    """Simple camera thread using OpenCV for macOS or fallback."""

    grabber_ready = pyqtSignal()
    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._device_index = 0
        self._stop_requested = False
        self.cap = None
        self._resolution = None

    def set_device_info(self, dev_info):
        self._device_index = int(dev_info)

    def set_resolution(self, resolution_tuple):
        # OpenCV backend currently ignores requested resolution
        self._resolution = resolution_tuple

    def run(self):
        try:
            self.cap = cv2.VideoCapture(self._device_index)
            if not self.cap.isOpened():
                raise RuntimeError(
                    f"Cannot open camera index {self._device_index}"
                )

            # Try to apply resolution if provided
            if self._resolution:
                w, h, _ = self._resolution
                if w and h:
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(w))
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(h))

            self.grabber_ready.emit()

            while not self._stop_requested:
                ret, frame = self.cap.read()
                if not ret:
                    continue
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb.shape
                bytes_per_line = ch * w
                image = QImage(
                    rgb.data, w, h, bytes_per_line, QImage.Format_RGB888
                )
                # Emit a copy to ensure memory safety
                self.frame_ready.emit(image.copy(), None)
        except Exception as e:
            log.error(f"OpenCVCameraThread error: {e}")
            self.error.emit(str(e), "")
        finally:
            if self.cap:
                self.cap.release()
                self.cap = None

    def stop(self):
        self._stop_requested = True
        self.wait(1000)
        if self.cap:
            self.cap.release()
            self.cap = None
