import cv2, math
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QImage, QPainter, QFont

class VideoThread(QThread):
    frame_ready = pyqtSignal(QImage, object)

    def __init__(self, camera_index=0):
        super().__init__()
        self.cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)

        # Try to set your desired resolution (e.g. 1920×1080)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        # Optionally set FPS
        self.cap.set(cv2.CAP_PROP_FPS, 30)

        # Then confirm what you actually got:
        w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        print(f"⚙️ Camera opened at {w}×{h} @ {fps:.1f} FPS")

        if not self.cap.isOpened():
            print(f"⚠️  Camera {camera_index} failed to open — falling back to test image.")
            self.cap = cv2.VideoCapture(camera_index)
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
                if not ret or frame is None:
                    # If capture failed, fall back to our placeholder
                    img = self.test_img
                    frame = None
                else:
                    # Convert BGR → RGB for display
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb.shape
                    bytes_per_line = ch * w
                    img = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
            else:
                # No camera detected → show placeholder at ~10 Hz
                img = self.test_img
                frame = None
                self.msleep(100)

            # Always emit both values (QImage, raw frame or None)
            self.frame_ready.emit(img, frame)

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()