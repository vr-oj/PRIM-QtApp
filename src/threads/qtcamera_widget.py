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

    def set_active_camera(self, camera_id: int, camera_description: str = ""):
        log.info(
            f"Attempting to set active camera to ID: {camera_id} ('{camera_description}')"
        )

        # Stop any existing thread
        if self._camera_thread:
            self._camera_thread.stop()
            self._camera_thread = None

        self.camera_id = camera_id
        self.camera_description = camera_description

        if camera_id < 0:
            # No camera selected
            self._update_placeholder_text()
            self.camera_resolutions_updated.emit([])
            self.camera_properties_updated.emit({})
            return True

        # Try to open with OpenCV to test availability
        cap = cv2.VideoCapture(self.camera_id, cv2.CAP_DSHOW)
        if not cap.isOpened():
            log.error(f"Cannot open camera ID {self.camera_id}")
            self.camera_error.emit(f"Cannot open camera {self.camera_id}", -1)
            self._update_placeholder_text(
                f"Error: Could not open camera {self.camera_id}"
            )
            self.camera_resolutions_updated.emit([])
            self.camera_properties_updated.emit({})
            return False

        # Query actual sensor size
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        self.full_frame_width = w
        self.full_frame_height = h
        log.info(f"Camera {camera_id} resolution: {w}x{h}")

        # ─── Launch new CameraThread with correct signature ─────────────────
        # pick a down‐sampled preview FPS
        raw_fps = (
            getattr(self.active_profile, "default_fps", 30)
            if self.active_profile
            else 30
        )
        preview_fps = min(raw_fps, 15)

        # NOTE: CameraThread.__init__ is now (device_index, fps, parent)
        self._camera_thread = CameraThread(
            device_index=camera_id, fps=preview_fps, parent=self
        )
        self._camera_thread.frameReady.connect(self._on_thread_frame)
        self._camera_thread.start()
        # ───────────────────────────────────────────────────────────────────

        # emit resolutions / properties for the UI
        self.camera_resolutions_updated.emit([f"{w}x{h}"])
        self.query_and_emit_camera_properties()

        return True

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
