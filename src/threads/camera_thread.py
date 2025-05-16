from PyQt5.QtCore import QThread, pyqtSignal
import cv2
from PyQt5.QtGui import QImage

class CameraThread(QThread):
    frameReady = pyqtSignal(QImage, object)

    def __init__(self, device_index=0, display_width=None, display_height=None, fps=30, parent=None):
        super().__init__(parent)
        self.device_index = device_index
        # these control only the **down-scale** for the UI
        self.display_width  = display_width
        self.display_height = display_height
        self.fps = fps
        self._running = True

    def run(self):
        cap = None
        try:
            # Try MSMF first, fallback to DSHOW
            cap = cv2.VideoCapture(self.device_index, cv2.CAP_MSMF)
            if not cap.isOpened():
                cap.release()
                cap = cv2.VideoCapture(self.device_index, cv2.CAP_DSHOW)
            if not cap.isOpened():
                return

            # Drop stale frames
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            delay = int(1000 / self.fps)

            while getattr(self, "_running", True):
                ret, full_frame = cap.read()
                if not ret:
                    continue

                # down‐scale to (self.display_width, self.display_height) if set …
                # convert to QImage → qt_img
                # bgr_for_rec = full_frame.copy()
                self.frameReady.emit(qt_img, bgr_for_rec)
                self.msleep(delay)
        finally:
            if cap is not None:
                cap.release()

    def stop(self):
        self._running = False
        self.wait()
