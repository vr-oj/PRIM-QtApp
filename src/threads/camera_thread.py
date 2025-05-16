# camera_thread.py
from PyQt5.QtCore import QThread, pyqtSignal
import cv2
from PyQt5.QtGui import QImage

class CameraThread(QThread):
    frameReady = pyqtSignal(QImage)

    def __init__(self, device_index=0, width=None, height=None, fps=30, parent=None):
        super().__init__(parent)
        self.device_index = device_index
        self.width = width
        self.height = height
        self.fps = fps
        self._running = True

    def run(self):
        cap = cv2.VideoCapture(self.device_index)
        if self.width and self.height:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        delay = int(1000 / self.fps)
        while self._running:
            ret, frame = cap.read()
            if not ret:
                continue
            # convert BGR→RGB
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, _ = rgb.shape
            qt_img = QImage(rgb.data, w, h, 3*w, QImage.Format_RGB888)
            self.frameReady.emit(qt_img)
            self.msleep(delay)

        cap.release()

    def stop(self):
        self._running = False
        self.wait()
