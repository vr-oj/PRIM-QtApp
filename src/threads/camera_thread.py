from PyQt5.QtCore import QThread, pyqtSignal
import cv2
from PyQt5.QtGui import QImage


class CameraThread(QThread):
    """
    Continuously grabs full-resolution frames from a camera, emits a QImage for preview,
    and exposes full BGR frames for recording.
    """

    frameReady = pyqtSignal(QImage, object)

    def __init__(self, device_index=0, fps=30, parent=None):
        super().__init__(parent)
        self.device_index = device_index
        self.fps = fps
        self._running = False
        # will be set after opening the camera
        self.frame_size = None  # (width, height)

    def run(self):
        self._running = True
        cap = cv2.VideoCapture(self.device_index, cv2.CAP_MSMF)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(self.device_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            return  # failed to open camera

        # query full sensor resolution
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.frame_size = (w, h)

        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        delay_ms = int(1000 / self.fps)

        while self._running:
            ret, full_frame = cap.read()
            if not ret:
                continue

            # convert BGR -> RGB for QImage
            rgb = cv2.cvtColor(full_frame, cv2.COLOR_BGR2RGB)
            height, width, _ = rgb.shape
            bytes_per_line = 3 * width
            qt_img = QImage(
                rgb.data,
                width,
                height,
                bytes_per_line,
                QImage.Format_RGB888,
            )

            # emit full-resolution preview image + raw frame
            self.frameReady.emit(qt_img, full_frame)

            self.msleep(delay_ms)

        # cleanup
        if cap.isOpened():
            cap.release()

    def stop(self):
        """Stops the capture thread and waits for it to finish."""
        self._running = False
        self.wait()
