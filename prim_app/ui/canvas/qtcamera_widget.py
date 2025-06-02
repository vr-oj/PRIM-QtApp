# prim_app/ui/canvas/qtcamera_widget.py

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
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

        # (1) The QLabel where frames will be painted
        self._label = QLabel("Camera Off")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setFixedSize(640, 480)
        self.layout().addWidget(self._label, alignment=Qt.AlignCenter)

        # (2) We will not start the thread here; MainWindow does it.
        #     But still create the thread so nothing breaks if someone wires it directly.
        self._cam_thread = SDKCameraThread()
        self._cam_thread.frame_ready.connect(self._on_frame_ready)
        self._cam_thread.error.connect(self._on_error)

    def update_image(self, image: QImage):
        """
        Public method: receives a QImage from MainWindow (via SDKCameraThread.frame_ready),
        converts it to QPixmap and displays it.
        """
        pix = QPixmap.fromImage(image)
        self._label.setPixmap(pix.scaled(self._label.size(), Qt.KeepAspectRatio))

    def clear_image(self):
        """
        Public method to clear the QLabel, showing “Camera Off”.
        """
        self._label.clear()
        self._label.setText("⏺ Camera Off")

    @pyqtSlot(QImage, object)
    def _on_frame_ready(self, image: QImage, raw):
        """
        Private slot (in case someone starts the internal thread directly).
        Converts QImage → QPixmap and displays it.
        """
        pix = QPixmap.fromImage(image)
        self._label.setPixmap(pix.scaled(self._label.size(), Qt.KeepAspectRatio))

    @pyqtSlot(str, str)
    def _on_error(self, msg: str, code: str):
        """
        Private error slot (in case MainWindow doesn't catch it).
        """
        self._label.setText(f"❗ {msg}")