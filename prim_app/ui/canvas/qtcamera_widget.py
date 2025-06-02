from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QPixmap, QImage

from threads.sdk_camera_thread import SDKCameraThread


class QtCameraWidget(QWidget):
    """
    Simplest camera widget: a QLabel to show frames.
    Internally starts/stops an SDKCameraThread that does the grabbing.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # ─── Layout for the QLabel ────────────────────────────────────────────
        vlay = QVBoxLayout(self)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(0)

        # 1) The QLabel where frames will be painted (and a placeholder text)
        self._label = QLabel("⏺ Camera Off", self)
        self._label.setAlignment(Qt.AlignCenter)
        # Fix the size here if you want a different default; main_window can resize it later
        self._label.setFixedSize(640, 480)
        vlay.addWidget(self._label)

        # 2) Create exactly one SDKCameraThread here
        #    We store it as self._cam_thread so main_window can refer to it via camera_widget._cam_thread
        self._cam_thread = SDKCameraThread(parent=self)
        # Connect signals to our slots
        self._cam_thread.frame_ready.connect(self._on_frame_ready)
        self._cam_thread.error.connect(self._on_error)

    @pyqtSlot(QImage, object)
    def _on_frame_ready(self, image: QImage, raw):
        """
        Receives QImage + raw NumPy array from SDKCameraThread.
        Converts QImage → QPixmap and displays it, maintaining aspect ratio.
        """
        pix = QPixmap.fromImage(image)
        # Always scale to fit the label's size, preserving aspect ratio
        self._label.setPixmap(pix.scaled(self._label.size(), Qt.KeepAspectRatio))

    @pyqtSlot(str, str)
    def _on_error(self, msg: str, code: str):
        """
        If anything goes wrong in the grab thread, show the error text in the QLabel.
        """
        # Overwrite label text with a warning icon + message
        self._label.setText(f"❗ {msg}")