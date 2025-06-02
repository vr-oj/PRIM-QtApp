from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore   import Qt, pyqtSlot
from PyQt5.QtGui    import QPixmap, QImage

class QtCameraWidget(QWidget):
    """
    Simplest camera widget: a QLabel to show frames. The parent (MainWindow)
    will connect `SDKCameraThread.frame_ready` → `_on_frame_ready`.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayout(QVBoxLayout())

        self._label = QLabel("Camera Off")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("background-color: black; color: white;")
        self._label.setFixedSize(640, 480)
        self.layout().addWidget(self._label)

    @pyqtSlot(QImage, object)
    def _on_frame_ready(self, image: QImage, raw):
        # Called whenever SDKCameraThread emits a new QImage
        pix = QPixmap.fromImage(image)
        self._label.setPixmap(pix.scaled(self._label.size(), Qt.KeepAspectRatio))

    def clear_image(self):
        # Reset to a black “Camera Off” placeholder
        self._label.clear()
        self._label.setText("Camera Off")
        self._label.setStyleSheet("background-color: black; color: white;")