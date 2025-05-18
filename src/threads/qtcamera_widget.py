import cv2
import logging
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QImage, QPixmap, QFont
from threads.camera_thread import CameraThread

log = logging.getLogger(__name__)


class QtCameraWidget(QWidget):
    """
    Shows a live feed scaled to this widget, and provides full-resolution frames for recording.
    """

    frame_ready = pyqtSignal(QImage, object)
    camera_error = pyqtSignal(str, int)
    camera_resolutions_updated = pyqtSignal(list)
    camera_properties_updated = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Preview label
        self.viewfinder_label = QLabel(self)
        self.viewfinder_label.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(12)
        self.viewfinder_label.setFont(font)
        self.viewfinder_label.setScaledContents(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.viewfinder_label)

        self._camera_thread = None
        self._last_pixmap = None

    def set_active_camera(self, camera_id: int):
        # Stop any existing capture
        if self._camera_thread:
            self._camera_thread.stop()
            self._camera_thread = None

        # Launch new camera thread
        self._camera_thread = CameraThread(device_index=camera_id)
        self._camera_thread.frameReady.connect(self._on_thread_frame)
        self._camera_thread.start()

    def _on_thread_frame(self, qimage: QImage, bgr_frame):
        # Display the downscaled preview
        pix = QPixmap.fromImage(qimage)
        self._last_pixmap = pix
        self._update_displayed_pixmap()
        # Emit full-resolution frame for recording
        self.frame_ready.emit(qimage, bgr_frame)

    def _update_displayed_pixmap(self):
        if self._last_pixmap and not self._last_pixmap.isNull():
            scaled = self._last_pixmap.scaled(
                self.viewfinder_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.viewfinder_label.setPixmap(scaled)
        else:
            self.viewfinder_label.clear()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_displayed_pixmap()

    def closeEvent(self, event):
        if self._camera_thread:
            self._camera_thread.stop()
        super().closeEvent(event)
