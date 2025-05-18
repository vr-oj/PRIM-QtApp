import logging
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QImage, QPixmap, QFont
from .sdk_camera_thread import SDKCameraThread

log = logging.getLogger(__name__)


class QtCameraWidget(QWidget):
    """
    Shows a live feed (scaled in the UI) and provides
    full-resolution frames for recording.
    """

    # preview QImage + full-res ndarray
    frame_ready = pyqtSignal(QImage, object)
    # inform MainWindow of available resolution
    camera_resolutions_updated = pyqtSignal(list)
    camera_error = pyqtSignal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Preview label
        self.viewfinder = QLabel(self)
        self.viewfinder.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(12)
        self.viewfinder.setFont(font)
        self.viewfinder.setScaledContents(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.viewfinder)

        self._camera_thread = None
        self._last_pixmap = None

    def set_active_camera(self, camera_id: int, camera_description: str = ""):
        # stop old thread
        if self._camera_thread:
            self._camera_thread.stop()
            self._camera_thread = None

        if camera_id < 0:
            # no camera: clear preview, emit empty
            self.viewfinder.clear()
            self.camera_resolutions_updated.emit([])
            return True

        # start TIS SDK thread
        self._camera_thread = SDKCameraThread(exposure=20000, parent=self)
        self._camera_thread.frame_ready.connect(self._on_sdk_frame)
        self._camera_thread.start()

        # (Optional) emit native resolution if needed
        # w, h = self._camera_thread.get_resolution()
        # self.camera_resolutions_updated.emit([f"{w}x{h}"])

        return True

    def _on_sdk_frame(self, qimg: QImage):
        """Handle incoming QImage frames from the SDK thread"""
        # update display
        self._last_pixmap = QPixmap.fromImage(qimg)
        self._update_display()
        # forward to recorder (raw array not provided here)
        self.frame_ready.emit(qimg, None)

    def _update_display(self):
        if self._last_pixmap and not self._last_pixmap.isNull():
            scaled = self._last_pixmap.scaled(
                self.viewfinder.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.viewfinder.setPixmap(scaled)
        else:
            self.viewfinder.clear()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._update_display()

    def closeEvent(self, ev):
        if self._camera_thread:
            self._camera_thread.stop()
        super().closeEvent(ev)
