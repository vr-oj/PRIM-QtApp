import logging
import time
import cv2
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class GenericCameraThread(QThread):
    """
    A fallback camera thread using OpenCV's VideoCapture. Emits
    the same signals as SDKCameraThread.
    """

    frame_ready = pyqtSignal(QImage, object)
    camera_resolutions_available = pyqtSignal(list)
    camera_properties_updated = pyqtSignal(dict)
    camera_error = pyqtSignal(str, str)

    def __init__(
        self,
        index=0,
        target_fps=20.0,
        desired_width=None,
        desired_height=None,
        parent=None,
    ):
        super().__init__(parent)
        self.index = index
        self.target_fps = target_fps
        self.desired_width = desired_width
        self.desired_height = desired_height
        self._stop_requested = False
        self.cap = None

    def request_stop(self):
        self._stop_requested = True
        log.debug("GenericCameraThread: stop requested")

    def run(self):
        try:
            # Try DirectShow backend on Windows for better compatibility
            self.cap = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)
            if not self.cap.isOpened():
                raise RuntimeError(f"Cannot open camera index {self.index}")

            # Apply desired resolution if requested
            if self.desired_width:
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(self.desired_width))
            if self.desired_height:
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(self.desired_height))

            # Read back actual resolution and emit
            w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.camera_resolutions_available.emit([f"{w}x{h}"])
            self.camera_properties_updated.emit({})

            frame_interval = 1.0 / self.target_fps
            while not self._stop_requested:
                ret, frame = self.cap.read()
                if not ret:
                    time.sleep(0.01)
                    continue

                # Convert BGR → RGB for Qt
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                hh, ww, ch = rgb.shape
                stride = ch * ww
                qimg = QImage(rgb.data, ww, hh, stride, QImage.Format_RGB888)
                if not qimg.isNull():
                    self.frame_ready.emit(qimg.copy(), rgb.tobytes())

                time.sleep(frame_interval)

        except Exception as e:
            log.exception("GenericCameraThread error")
            self.camera_error.emit(str(e), "GenericCameraError")

        finally:
            if self.cap:
                self.cap.release()
            log.info("GenericCameraThread stopped")
