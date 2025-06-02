# ui/canvas/qtcamera_widget.py

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QPixmap, QImage

class QtCameraWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setLayout(QVBoxLayout())
        self._label = QLabel("Camera Off")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setFixedSize(640, 480)
        self.layout().addWidget(self._label, alignment=Qt.AlignCenter)

    @pyqtSlot(QImage)
    def update_image(self, qimage: QImage):
        """Called by MainWindow.frame_ready → display the new frame."""
        pix = QPixmap.fromImage(qimage)
        self._label.setPixmap(pix.scaled(self._label.size(), Qt.KeepAspectRatio))

    def clear_image(self):
        """Called when the camera stops, to reset the label."""
        self._label.clear()
        self._label.setText("⏺ Camera Off")