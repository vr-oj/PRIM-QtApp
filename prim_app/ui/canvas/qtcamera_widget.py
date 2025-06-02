# prim_app/ui/canvas/qtcamera_widget.py

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QPixmap, QImage

from threads.sdk_camera_thread import SDKCameraThread


class QtCameraWidget(QWidget):
    """
    Simplest camera widget: a QLabel to show frames, and a black placeholder before feed.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # 1) Give this widget exactly one QVBoxLayout:
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        # 2) Create a QLabel that will hold either a black pixmap or live frames
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setFixedSize(640, 480)

        # Start with a solid-black pixmap (so it looks like a “viewfinder”):
        black = QPixmap(640, 480)
        black.fill(Qt.black)
        self._label.setPixmap(black)
        # (Optional) overlay “Camera Off” text in white until first frame:
        self._label.setStyleSheet("color: white;")
        self._label.setText("Camera Off")

        vbox.addWidget(self._label, alignment=Qt.AlignCenter)

        # 3) Prepare the camera thread (but do NOT start it yet)
        self._cam_thread = SDKCameraThread(parent=self)
        self._cam_thread.frame_ready.connect(self._on_frame_ready)
        self._cam_thread.error.connect(self._on_error)

    @pyqtSlot(QImage, object)
    def _on_frame_ready(self, image: QImage, raw):
        """
        Receives QImage + numpy array from SDKCameraThread.
        Converts QImage → QPixmap and displays it.
        """
        # Convert the QImage into a QPixmap and scale to fit the label:
        pix = QPixmap.fromImage(image)
        self._label.setPixmap(pix.scaled(
            self._label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        ))

    @pyqtSlot(str, str)
    def _on_error(self, msg: str, code: str):
        """
        If anything goes wrong, show the error text in the QLabel.
        """
        self._label.setText(f"❗ {msg}")

    def start_camera(self):
        if not self._cam_thread.isRunning():
            # Once MainWindow tells us to start, this call will begin grabbing
            self._cam_thread.start()

    def stop_camera(self):
        if self._cam_thread.isRunning():
            self._cam_thread.stop()
            # Restore placeholder:
            black = QPixmap(640, 480)
            black.fill(Qt.black)
            self._label.setPixmap(black)
            self._label.setText("Camera Off")