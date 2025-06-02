# prim_app/ui/canvas/qtcamera_widget.py

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QImage


class QtCameraWidget(QWidget):
    """
    Simplest camera widget: a QLabel to show frames.
    The actual SDKCameraThread lives in MainWindow,
    which will call update_image() or clear_image().
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # Create a QLabel to show incoming frames
        self._label = QLabel("Camera Off")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setFixedSize(640, 480)

        # Put the label into a QVBoxLayout so it expands
        layout = QVBoxLayout(self)
        layout.addWidget(self._label, alignment=Qt.AlignCenter)

    def update_image(self, image: QImage):
        """
        Called by MainWindow (in response to SDKCameraThread.frame_ready).
        Convert QImage → QPixmap and display it here in the QLabel.
        """
        pix = QPixmap.fromImage(image)
        self._label.setPixmap(pix.scaled(self._label.size(), Qt.KeepAspectRatio))

    def clear_image(self):
        """
        Called by MainWindow when stopping the camera.
        Resets the QLabel to show “Camera Off.”
        """
        self._label.setPixmap(QPixmap())
        self._label.setText("⏺ Camera Off")