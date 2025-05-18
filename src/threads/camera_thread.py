from pycromanager import Core
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage


class CameraThread(QThread):
    frameReady = pyqtSignal(QImage, object)

    def __init__(self, fps=20, parent=None):
        super().__init__(parent)
        self.core = Core()
        self.fps = fps
        self._stop = threading.Event()
        # query once
        w = self.core.get_image_width()
        h = self.core.get_image_height()
        self.frame_size = (w, h)

    def run(self):
        delay_ms = int(1000 / self.fps)
        self.core.start_continuous_sequence_acquisition(0)
        try:
            while not self._stop.is_set():
                tagged = self.core.get_tagged_image()
                img = tagged.pix.reshape(self.frame_size[1], self.frame_size[0])
                # full-res array for recording
                arr = img.copy()
                # convert for preview
                rgb = (
                    cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
                    if img.ndim == 2
                    else cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                )
                h, w, _ = rgb.shape
                qt = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
                self.frameReady.emit(qt, arr)
                self.msleep(delay_ms)
        finally:
            self.core.stop_sequence_acquisition()

    def stop(self):
        self._stop.set()
        self.wait()
