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
        self._running = True
        cap = None
        try:
            # Try MSMF, fallback to DSHOW
            cap = cv2.VideoCapture(self.device_index, cv2.CAP_MSMF)
            if not cap.isOpened():
                cap.release()
                cap = cv2.VideoCapture(self.device_index, cv2.CAP_DSHOW)
            if not cap.isOpened():
                return

            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            delay = int(1000 / self.fps)

            while self._running:
                ret, full_frame = cap.read()
                if not ret:
                    continue

                # down-scale for preview
                if self.display_width and self.display_height:
                    disp = cv2.resize(
                        full_frame,
                        (self.display_width, self.display_height),
                        interpolation=cv2.INTER_LINEAR,
                    )
                else:
                    disp = full_frame

                # convert to QImage
                rgb = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)
                h, w, _ = rgb.shape
                bytes_per_line = 3 * w
                qt_img = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)

                # full-res BGR copy for recording/measures
                bgr_for_rec = full_frame.copy()

                # emit both
                self.frameReady.emit(qt_img, bgr_for_rec)

                self.msleep(delay)

        finally:
            if cap is not None and cap.isOpened():
                cap.release()

    def stop(self):
        self._running = False
        self.wait()