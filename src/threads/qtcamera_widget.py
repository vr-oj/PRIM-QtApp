import logging
import imagingcontrol4 as ic4
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from PyQt5.QtCore import pyqtSignal, pyqtSlot
from PyQt5.QtGui import QImage

from .sdk_camera_thread import SDKCameraThread

log = logging.getLogger(__name__)


class QtCameraWidget(QWidget):
    """Simplified widget: starts camera thread on show and displays frames."""

    frame_ready = pyqtSignal(QImage, object)
    camera_error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Single-run, full sensor
        self._camera_thread = None
        layout = QVBoxLayout(self)
        # use a QLabel or QGraphicsView for preview, e.g. QLabel
        from PyQt5.QtWidgets import QLabel

        self._preview = QLabel(alignment=Qt.AlignCenter)
        layout.addWidget(self._preview)
        self.setLayout(layout)

    def start(self):
        if self._camera_thread:
            return
        self._camera_thread = SDKCameraThread(parent=self)
        self._camera_thread.frame_ready.connect(self._on_frame)
        self._camera_thread.camera_error.connect(self.camera_error.emit)
        self._camera_thread.start()

    def stop(self):
        if not self._camera_thread:
            return
        self._camera_thread.request_stop()
        self._camera_thread.wait(2000)
        self._camera_thread = None

    @pyqtSlot(QImage, object)
    def _on_frame(self, img: QImage, data):
        # simple display
        from PyQt5.QtGui import QPixmap

        self._preview.setPixmap(QPixmap.fromImage(img))
        self.frame_ready.emit(img, data)

    def showEvent(self, e):
        super().showEvent(e)
        self.start()

    def closeEvent(self, e):
        self.stop()
        super().closeEvent(e)
