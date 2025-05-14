import cv2, math, sys
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui  import QImage, QPainter, QFont

class VideoThread(QThread):
    frame_ready = pyqtSignal(QImage, object)

    def __init__(self, camera_index=0):
        super().__init__()

        # 1) Choose preferred backend per OS
        if sys.platform == "darwin":
            preferred = [cv2.CAP_AVFOUNDATION, cv2.CAP_ANY]
        elif sys.platform.startswith("win"):
            preferred = [cv2.CAP_DSHOW, cv2.CAP_ANY]
        else:
            preferred = [cv2.CAP_ANY]

        # 2) Try opening the camera with each backend until one works
        self.cap = None
        for backend in preferred:
            cap = cv2.VideoCapture(camera_index, backend)
            if cap.isOpened():
                self.cap = cap
                print(f"⚙️  Opened camera {camera_index} with backend {backend}")
                break
            cap.release()

        # 3) If none succeeded, fall back to placeholder
        if not self.cap or not self.cap.isOpened():
            print(f"⚠️  Camera {camera_index} failed to open with any backend")
            self.cap = None
            self.test_img = self._make_test_image(640, 480, "No Video")
        else:
            # Optional: set your desired resolution & FPS here
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT,1080)
            self.cap.set(cv2.CAP_PROP_FPS,30)
            w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = self.cap.get(cv2.CAP_PROP_FPS)
            print(f"📐 Camera running at {w}×{h} @ {fps:.1f} FPS")

        self.running = True


    def _make_test_image(self, w,h,text):
        img = QImage(w,h,QImage.Format_RGB32)
        img.fill(Qt.darkGray)
        p = QPainter(img); p.setPen(Qt.white); p.setFont(QFont("Arial",24))
        p.drawText(img.rect(), Qt.AlignCenter, text); p.end()
        return img

    def run(self):
        while self.running:
            if self.cap:
                ret, frame = self.cap.read()
                if not ret or frame is None:
                    img, frame = self.test_img, None
                else:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h,w,ch = rgb.shape; line = ch*w
                    img = QImage(rgb.data,w,h,line,QImage.Format_RGB888)
            else:
                img, frame = self.test_img, None
                self.msleep(100)
            self.frame_ready.emit(img, frame)

    def stop(self):
        self.running = False
        if self.cap: self.cap.release()
