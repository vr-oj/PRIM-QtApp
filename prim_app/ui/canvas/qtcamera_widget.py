# prim_app/ui/canvas/qtcamera_widget.py

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QPixmap, QImage

from threads.sdk_camera_thread import SDKCameraThread


class QtCameraWidget(QWidget):
    """
    Simplest camera widget: a QLabel to show frames, and a button to start/stop.
    Internally starts/stops SDKCameraThread.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayout(QVBoxLayout())

        # 1) The QLabel where frames will be painted
        self._label = QLabel("⏺ Camera Off", alignment=Qt.AlignCenter)
        self._label.setFixedSize(640, 480)  # adjust if you want a different size
        self.layout().addWidget(self._label)

        # 2) A Start/Stop button
        self._btn = QPushButton("Start Camera")
        self.layout().addWidget(self._btn)

        # 3) Camera thread (not started yet)
        self._cam_thread = SDKCameraThread()
        # Connect signals from the thread to our slots
        self._cam_thread.frame_ready.connect(self._on_frame_ready)
        self._cam_thread.error.connect(self._on_error)

        # 4) Button toggles camera on/off
        self._btn.clicked.connect(self._toggle_camera)

    @pyqtSlot(QImage, object)
    def _on_frame_ready(self, image: QImage, raw):
        """
        Receives QImage + numpy array from SDKCameraThread.
        Converts QImage → QPixmap and displays it.
        """
        pix = QPixmap.fromImage(image)
        self._label.setPixmap(pix.scaled(self._label.size(), Qt.KeepAspectRatio))

    @pyqtSlot(str, str)
    def _on_error(self, msg: str, code: str):
        """
        If anything goes wrong, show the error text in the QLabel.
        """
        self._label.setText(f"❗ {msg}")

    def _toggle_camera(self):
        """
        Start or stop the camera thread on button click.
        """
        if not self._cam_thread.isRunning():
            self._btn.setText("Stop Camera")
            self._cam_thread.start()
        else:
            self._btn.setText("Start Camera")
            self._cam_thread.stop()
            self._label.setText("⏺ Camera Off")
