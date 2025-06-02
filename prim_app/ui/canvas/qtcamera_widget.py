# File: prim_app/ui/canvas/qtcamera_widget.py

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QPixmap, QImage

class QtCameraWidget(QWidget):
    """
    Simplest camera widget: a QLabel to show frames.
    Exposes:
      - update_image(QImage) → display the new frame.
      - clear_image() → show a “Camera Off” placeholder.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayout(QVBoxLayout())
        self._label = QLabel("⏺ Camera Off")
        self._label.setAlignment(Qt.AlignCenter)
        # Give it a default size; you can change to suit your UI.
        self._label.setFixedSize(640, 480)
        # Insert into the widget’s layout:
        self.layout().addWidget(self._label, alignment=Qt.AlignCenter)

    @pyqtSlot(QImage)
    def update_image(self, image: QImage):
        """Convert QImage → QPixmap, scale to fit, and show."""
        pix = QPixmap.fromImage(image)
        self._label.setPixmap(pix.scaled(self._label.size(), Qt.KeepAspectRatio))

    def clear_image(self):
        """Reset the label to “Camera Off”."""
        self._label.clear()
        self._label.setText("⏺ Camera Off")