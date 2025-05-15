import cv2
from PyQt5.QtWidgets    import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore       import QTimer, pyqtSignal, Qt, QSize
from PyQt5.QtGui        import QImage, QPixmap

class QtCameraWidget(QWidget):
    frame_ready = pyqtSignal(QImage, object)
    camera_error = pyqtSignal(str, int)
    camera_resolutions_updated = pyqtSignal(list)


    def __init__(self, camera_id: int = -1, parent=None):
        super().__init__(parent)
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self.label)

        # open the DSHOW capture
        self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        # optionally set resolution:
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 2448)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT,2048)

        # timer to pull frames
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._grab_frame)
        self.timer.start(30)  # ~33 fps

    def _grab_frame(self):
        ret, frame = self.cap.read()
        if not ret:
            return
        # BGR → RGB
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        self.label.setPixmap(QPixmap.fromImage(qimg))
        self.frame_ready.emit(qimg, None)

    def closeEvent(self, event):
        self.timer.stop()
        self.cap.release()
        super().closeEvent(event)
