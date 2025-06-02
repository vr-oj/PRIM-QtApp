# File: prim_app/ui/canvas/qtcamera_widget.py

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QPixmap, QImage


class QtCameraWidget(QWidget):
    """
    A simple widget that displays QImage frames in a QLabel.
    The MainWindow / SDKCameraThread will push each new QImage by calling update_image().
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # 1) Create a QLabel to show frames:
        self._label = QLabel("Camera Off")
        self._label.setAlignment(Qt.AlignCenter)

        # 2) Put that QLabel into our layout:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

        # 3) Fix a default size so it doesn't collapse; you can change as desired:
        self._label.setFixedSize(640, 480)

    @pyqtSlot(QImage)
    def update_image(self, image: QImage):
        """
        Public slot: when a new QImage arrives from SDKCameraThread, this is called.
        We convert to QPixmap and scale it to fit the label (with aspect‐ratio).
        """
        pix = QPixmap.fromImage(image)
        self._label.setPixmap(pix.scaled(self._label.size(), Qt.KeepAspectRatio))

    def clear_image(self):
        """
        Call this to show “Camera Off” text (or you can set a default pixmap).
        """
        self._label.setText("⏺ Camera Off")
        self._label.setPixmap(QPixmap())  # clear any old pixmap