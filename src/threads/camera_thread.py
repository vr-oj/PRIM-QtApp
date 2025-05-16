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
        cap = cv2.VideoCapture(self.device_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
             return
        delay = int(1000 / self.fps)
        while self._running:
            ret, full_frame = cap.read()
            if not ret:
                continue
            # 1) Keep the full-res frame for measurements:
            bgr_for_measurement = full_frame

            # 2) Downscale a copy just for display:
            if self.display_width and self.display_height:
                disp = cv2.resize(full_frame,
                                  (self.display_width, self.display_height),
                                  interpolation=cv2.INTER_LINEAR)
            else:
                disp = full_frame
            # BGR→RGB and wrap in QImage
            rgb_disp = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)
            h, w, _ = rgb_disp.shape
            bytes_per_line = 3 * w
            qt_img = QImage(rgb_disp.data, w, h, bytes_per_line, QImage.Format_RGB888)

            # emit both display image and full-res array
            self.frameReady.emit(qt_img, bgr_for_measurement)
            self.msleep(delay)

        cap.release()

    def stop(self):
        self._running = False
        self.wait()
