import logging
import imagingcontrol4 as ic4
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QOpenGLWidget,
)
from PyQt5.QtCore import pyqtSignal, Qt, pyqtSlot, QTimer
from PyQt5.QtGui import QImage, QPixmap

from .sdk_camera_thread import SDKCameraThread

log = logging.getLogger(__name__)


class GLCameraView(QGraphicsView):
    """
    A QGraphicsView that uses QOpenGLWidget viewport for GPU-accelerated rendering,
    auto-fitting the frame to its view.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        scene = QGraphicsScene(self)
        self.setScene(scene)
        self._item = QGraphicsPixmapItem()
        scene.addItem(self._item)
        self.setViewport(QOpenGLWidget())
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setAlignment(Qt.AlignCenter)

    def update_frame(self, qimg: QImage):
        pix = QPixmap.fromImage(qimg)
        self._item.setPixmap(pix)
        # keep full frame visible
        self.fitInView(self._item, Qt.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # re-fit on resize
        self.fitInView(self._item, Qt.KeepAspectRatio)


class QtCameraWidget(QWidget):
    """
    Displays live camera feed via SDKCameraThread using OpenGL for performance.
    Manages camera selection, resolution, and basic properties.
    """

    frame_ready = pyqtSignal(QImage, object)
    camera_resolutions_updated = pyqtSignal(list)
    camera_properties_updated = pyqtSignal(dict)
    camera_error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Start in full-frame by default
        self.current_target_fps = 20.0
        self.current_width = None  # None => full sensor
        self.current_height = None
        self.current_pixel_format = "Mono8"
        self._current_roi = (0, 0, 0, 0)
        # Thread and storage
        self._camera_thread = None
        self._active_device_info: ic4.DeviceInfo = None
        # Debounce timers
        self._setup_debounce_timers()
        # OpenGL-backed viewfinder
        self.viewfinder = GLCameraView(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.viewfinder)
        self.setLayout(layout)

    def _setup_debounce_timers(self):
        self._exp_pending = None
        self._gain_pending = None
        self._exp_timer = QTimer(self)
        self._exp_timer.setSingleShot(True)
        self._exp_timer.setInterval(100)
        self._exp_timer.timeout.connect(self._apply_pending_exposure)
        self._gain_timer = QTimer(self)
        self._gain_timer.setSingleShot(True)
        self._gain_timer.setInterval(100)
        self._gain_timer.timeout.connect(self._apply_pending_gain)

    def _cleanup_camera_thread(self):
        log.debug("Cleaning up camera thread...")
        if self._camera_thread:
            thread = self._camera_thread
            self._camera_thread = None
            if thread.isRunning():
                thread.request_stop()
                if not thread.wait(3000):
                    thread.terminate()
            try:
                thread.frame_ready.disconnect(self._on_sdk_frame_received)
                thread.camera_error.disconnect(self._on_camera_thread_error_received)
                thread.camera_resolutions_available.disconnect(
                    self.camera_resolutions_updated
                )
                thread.camera_properties_updated.disconnect(
                    self.camera_properties_updated
                )
            except Exception:
                pass
            thread.deleteLater()

    @pyqtSlot(ic4.DeviceInfo)
    def set_active_camera_device(self, device_info: ic4.DeviceInfo = None):
        self._cleanup_camera_thread()
        self._active_device_info = device_info
        if not device_info:
            return
        self._start_new_camera_thread()

    def _start_new_camera_thread(self):
        if self._camera_thread:
            self._cleanup_camera_thread()
        if not self._active_device_info:
            return
        self._camera_thread = SDKCameraThread(
            device_info=self._active_device_info,
            target_fps=self.current_target_fps,
            desired_width=self.current_width,
            desired_height=self.current_height,
            desired_pixel_format=self.current_pixel_format,
            parent=self,
        )
        self._camera_thread.frame_ready.connect(self._on_sdk_frame_received)
        self._camera_thread.camera_error.connect(self._on_camera_thread_error_received)
        self._camera_thread.camera_resolutions_available.connect(
            self.camera_resolutions_updated
        )
        self._camera_thread.camera_properties_updated.connect(
            self.camera_properties_updated
        )
        self._camera_thread.start()

    @pyqtSlot(str)
    def set_active_resolution_str(self, resolution_str: str):
        if "x" in resolution_str:
            parts = resolution_str.split("x", 1)
            try:
                w = int(parts[0])
                h = int(parts[1].split()[0])
            except Exception:
                return
            if (w, h) != (self.current_width, self.current_height):
                self.current_width, self.current_height = w, h
                self._cleanup_camera_thread()
                self._start_new_camera_thread()

    @pyqtSlot(int)
    def set_exposure(self, exposure_us: int):
        self._exp_pending = exposure_us
        self._exp_timer.start()

    @pyqtSlot(float)
    def set_gain(self, gain_db: float):
        self._gain_pending = gain_db
        self._gain_timer.start()

    @pyqtSlot(bool)
    def set_auto_exposure(self, enable_auto: bool):
        if self._camera_thread and self._camera_thread.isRunning():
            self._camera_thread.update_auto_exposure(enable_auto)

    @pyqtSlot()
    def _apply_pending_exposure(self):
        if (
            self._camera_thread
            and hasattr(self, "_exp_pending")
            and self._exp_pending is not None
        ):
            self._camera_thread.update_auto_exposure(False)
            self._camera_thread.update_exposure(self._exp_pending)
        self._exp_pending = None

    @pyqtSlot()
    def _apply_pending_gain(self):
        if (
            self._camera_thread
            and hasattr(self, "_gain_pending")
            and self._gain_pending is not None
        ):
            self._camera_thread.update_gain(self._gain_pending)
        self._gain_pending = None

    @pyqtSlot(int, int, int, int)
    def set_software_roi(self, x: int, y: int, w: int, h: int):
        self._current_roi = (x, y, w, h)
        if self._camera_thread and self._camera_thread.isRunning():
            self._camera_thread.update_roi(x, y, w, h)

    @pyqtSlot()
    def reset_roi_to_default(self):
        """Reset Region Of Interest to full frame."""
        self.current_width = None
        self.current_height = None
        self._cleanup_camera_thread()
        self._start_new_camera_thread()

    @pyqtSlot(QImage, object)
    def _on_sdk_frame_received(self, qimg: QImage, frame_data: object):
        if qimg.isNull():
            return

        # software ROI: if the user has requested a sub-region, crop here
        x, y, w, h = self._current_roi
        if w > 0 and h > 0:
            try:
                cropped = qimg.copy(x, y, w, h)
            except Exception:
                cropped = qimg
        else:
            cropped = qimg

        self.viewfinder.update_frame(cropped)
        self.frame_ready.emit(cropped, frame_data)

    @pyqtSlot(str, str)
    def _on_camera_thread_error_received(self, message: str, code: str):
        self.camera_error.emit(message, code)

    def current_camera_is_active(self) -> bool:
        return bool(self._camera_thread and self._camera_thread.isRunning())
