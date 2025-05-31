# camera_view.py

from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt5.QtGui import QPixmap, QImage
import numpy as np
import logging

log = logging.getLogger(__name__)


class CameraView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.label = QLabel("Camera Feed")
        self.label.setStyleSheet("background-color: black;")
        self.label.setScaledContents(True)

        layout = QVBoxLayout()
        layout.addWidget(self.label)
        self.setLayout(layout)

    def set_frame(self, frame: np.ndarray):
        """Called by the camera thread to update the displayed image."""
        if frame.ndim == 2:
            fmt = QImage.Format_Grayscale8
        elif frame.shape[2] == 3:
            fmt = QImage.Format_RGB888
        else:
            log.warning("Unsupported frame format.")
            return

        h, w = frame.shape[:2]
        image = QImage(frame.data, w, h, frame.strides[0], fmt)
        self.label.setPixmap(QPixmap.fromImage(image))
