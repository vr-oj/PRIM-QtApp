import cv2
import threading
import time
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal


class OpenCVCameraThread(QThread):
    frame_ready = pyqtSignal(np.ndarray)
    camera_error = pyqtSignal(str)

    def __init__(self, device_index=0, parent=None):
        super().__init__(parent)
        self.device_index = device_index
        self._is_running = True
        self.capture = None

    def run(self):
        try:
            self.capture = cv2.VideoCapture(self.device_index)
            if not self.capture.isOpened():
                self.camera_error.emit("OpenCV failed to open camera.")
                return

            while self._is_running:
                ret, frame = self.capture.read()
                if not ret:
                    self.camera_error.emit("OpenCV failed to read frame.")
                    break
                self.frame_ready.emit(frame)
                time.sleep(1 / 30.0)  # 30 FPS

        except Exception as e:
            self.camera_error.emit(f"OpenCV camera thread error: {e}")

        finally:
            if self.capture:
                self.capture.release()

    def stop(self):
        self._is_running = False
        self.wait()
