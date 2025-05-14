import cv2, math, sys, os, logging, traceback
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui  import QImage, QPainter, QFont

# — configure logging —
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s"
)
log = logging.getLogger(__name__)

class VideoThread(QThread):
    frame_ready = pyqtSignal(QImage, object)

    def __init__(self, camera_index=0, preferred=None):
        # always call the base constructor first
        super().__init__()
        self.camera_index = camera_index
        self.running = False
        self.test_img = None
        log.debug(f"Initializing VideoThread(camera_index={camera_index})")

        try:
            # choose backends based on OS
            if sys.platform == "darwin":
                backends = [cv2.CAP_AVFOUNDATION, cv2.CAP_ANY]
            elif sys.platform.startswith("win"):
                backends = [cv2.CAP_DSHOW, cv2.CAP_ANY]
            else:
                backends = [cv2.CAP_ANY]

            # try to open the camera
            self.cap = None
            for backend in backends:
                cap = cv2.VideoCapture(self.camera_index, backend)
                if cap.isOpened():
                    self.cap = cap
                    log.info(f"Opened camera {self.camera_index} with backend {backend}")
                    break
                cap.release()

            # fallback to a placeholder image
            if not self.cap:
                log.warning(f"Camera {self.camera_index} failed to open with any backend")
                self.test_img = self._make_test_image(640, 480, "No Video")
            else:
                # optional: set resolution/fps
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT,1080)
                self.cap.set(cv2.CAP_PROP_FPS,30)
                w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                fps = self.cap.get(cv2.CAP_PROP_FPS)
                log.debug(f"Camera running at {w}×{h} @ {fps:.1f} FPS")

            # thread is ready to run
            self.running = True
        except Exception:
            log.exception("Error during VideoThread.__init__")
            # if init fails, create a fallback image so run() still emits something
            self.cap = None
            self.test_img = self._make_test_image(640, 480, "Init Error")
            self.running = False
            # re‑raise if you want to abort entirely:
            # raise

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
        log.debug("VideoThread started")
        try:
            while self.running:
                ret, frame = False, None

                if self.cap:
                    try:
                        ret, frame = self.cap.read()
                    except cv2.error as e:
                        log.exception("OpenCV read() error, falling back to test image")
                        ret, frame = False, None

                # if capture failed, display the test image
                if not ret or frame is None:
                    img = self.test_img or self._make_test_image(640, 480, "No Video")
                else:
                    # convert to RGB QImage
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, _ = frame.shape
                    img = QImage(frame.data, w, h, QImage.Format_RGB888)

                self.frame_ready.emit(img, frame)
        except Exception:
            log.exception("Unexpected error in VideoThread.run()")
        finally:
            self.running = False
        if getattr(self, 'cap', None):
            try:
                self.cap.release()
                log.debug(f"Camera {self.camera_index} released")
            except Exception:
                log.exception("Error releasing camera in run()")

    def stop(self):
        log.debug("stop() called for VideoThread")
        self.running = False
        # also release here in case run() is sleeping
        if getattr(self, 'cap', None):
            try:
                self.cap.release()
                log.debug(f"Camera {self.camera_index} released in stop()")
            except Exception:
                log.exception("Error releasing camera in stop()")
