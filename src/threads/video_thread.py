import cv2, math
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QImage, QPainter, QFont

class VideoThread(QThread):
    frame_ready = pyqtSignal(QImage, object)

    def __init__(self, camera_index=0):
        super().__init__()
        # Try macOS AVFoundation (you can omit the second arg on Windows)
        self.cap = cv2.VideoCapture(camera_index, cv2.CAP_AVFOUNDATION)
        if not self.cap.isOpened():
            print(f"⚠️  Camera {camera_index} failed to open — falling back to test image.")
            self.cap = None
            # create a placeholder image once
            self.test_img = self._make_test_image(640, 480, "No Video")
        self.running = True

    def _make_test_image(self, w, h, text):
        img = QImage(w, h, QImage.Format_RGB32)
        img.fill(Qt.darkGray)
        p = QPainter(img)
        p.setPen(Qt.white)
        p.setFont(QFont("Arial", 24))
        p.drawText(img.rect(), Qt.AlignCenter, text)
        p.end()
        return img

    def run(self):
        while self.running:
            if self.cap:
                ret, frame = self.cap.read()
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) if ret else None
                if not ret:
                    # emit the test image if grab fails
                    img = self.test_img
                else:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb.shape
                    bytes_per_line = ch * w
                    img = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
            else:
                # no camera → just emit the placeholder at ~10 Hz
                img = self.test_img
                self.msleep(100)

            self.frame_ready.emit(img, frame)

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()