# File: threads/qtcamera_widget.py
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QPixmap

from .sdk_camera_thread import SDKCameraThread


class QtCameraWidget(QWidget):
    """
    Simple widget that starts/stops SDKCameraThread and shows live frames in a QLabel.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayout(QVBoxLayout())
        self._label = QLabel("⏺ Camera Off", alignment=Qt.AlignCenter)
        self._label.setFixedSize(640, 480)  # or whatever size you prefer
        self.layout().addWidget(self._label)

        # A single button to start/stop the camera
        self._btn = QPushButton("Start Camera")
        self.layout().addWidget(self._btn)

        # Create the camera thread, but don’t start yet
        self._cam_thread = SDKCameraThread()
        self._cam_thread.frame_ready.connect(self._on_frame_ready)
        self._cam_thread.error.connect(self._on_error)

        self._btn.clicked.connect(self._toggle_camera)

    @pyqtSlot(QPixmap)
    def _on_frame_ready(self, image, raw):
        """
        Whenever the thread emits a new QImage, show it in the QLabel.
        """
        pix = QPixmap.fromImage(image)
        self._label.setPixmap(pix.scaled(self._label.size(), Qt.KeepAspectRatio))

    @pyqtSlot(str, str)
    def _on_error(self, msg, code):
        """
        Display error text if anything goes wrong.
        """
        self._label.setText(f"❗ {msg}")

    def _toggle_camera(self):
        if not self._cam_thread.isRunning():
            self._btn.setText("Stop Camera")
            self._cam_thread.start()
        else:
            self._btn.setText("Start Camera")
            self._cam_thread.stop()
            self._label.setText("⏺ Camera Off")
