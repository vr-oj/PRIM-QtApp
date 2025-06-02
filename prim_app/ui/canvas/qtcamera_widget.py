# File: prim_app/ui/canvas/qtcamera_widget.py
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QPixmap, QImage

class QtCameraWidget(QWidget):
    """
    Simplest camera widget: a QLabel to show frames, and no button here.
    MainWindow will drive start/stop via SDKCameraThread.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # Use a single QVBoxLayout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # The QLabel where frames will be painted
        self._label = QLabel("Camera Off", self)
        self._label.setAlignment(Qt.AlignCenter)
        # Fix the label’s “logical” size (you can adjust if you want a different preview size).
        self._label.setFixedSize(640, 480)

        layout.addWidget(self._label)

    @pyqtSlot(QImage)
    def update_image(self, image: QImage):
        """
        Public slot: receives a QImage from SDKCameraThread.  Convert → QPixmap and display.
        """
        pix = QPixmap.fromImage(image)
        # Scale to fit the QLabel, preserving aspect ratio
        scaled = pix.scaled(self._label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._label.setPixmap(scaled)

    def clear_image(self):
        """
        Public method: clear the QLabel back to “Camera Off”.
        """
        self._label.setPixmap(QPixmap())
        self._label.setText("⏺ Camera Off")