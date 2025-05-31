# camera_view.py

import logging
from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout, QSizePolicy
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import Qt, pyqtSlot

log = logging.getLogger(__name__)


class CameraView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.label = QLabel("Camera View", self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("background-color: black; color: white;")
        self.label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)
        self.setLayout(layout)

    @pyqtSlot(QImage)
    def set_frame(self, image: QImage):
        if not image or image.isNull():
            log.warning("Received null image in CameraView.")
            return
        pixmap = QPixmap.fromImage(image)
        self.label.setPixmap(
            pixmap.scaled(
                self.label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )
