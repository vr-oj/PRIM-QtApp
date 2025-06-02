# prim_app/ui/canvas/qtcamera_widget.py

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QPixmap, QImage


class QtCameraWidget(QWidget):
    """
    A simple “viewfinder” widget.  Exposes a slot `update_image(QImage)` that
    will be called whenever a new frame arrives.  Internally just holds a QLabel
    and paints each QImage into it, scaling to fit.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # Create a vertical layout and place a QLabel in it.
        self.setLayout(QVBoxLayout())
        self._label = QLabel("Camera Off")
        self._label.setAlignment(Qt.AlignCenter)
        # Give the label a fixed “preview” size; adjust as needed:
        self._label.setFixedSize(640, 480)
        self.layout().addWidget(self._label, alignment=Qt.AlignCenter)

    @pyqtSlot(QImage)
    def update_image(self, image: QImage):
        """
        Slot to receive a new QImage from SDKCameraThread.
        We convert to QPixmap and scale it to fit our QLabel.
        """
        if image is None or image.isNull():
            return

        pix = QPixmap.fromImage(image)
        # Scale to fit the label, keeping aspect ratio
        scaled = pix.scaled(self._label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._label.setPixmap(scaled)

    @pyqtSlot()
    def clear_image(self):
        """
        Clear the viewfinder (set a placeholder text and remove any pixmap).
        """
        self._label.clear()
        self._label.setText("⏺ Camera Off")