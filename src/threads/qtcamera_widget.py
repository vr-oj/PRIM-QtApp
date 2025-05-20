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
from PyQt5.QtCore import pyqtSignal, Qt, pyqtSlot, QTimer, QRectF
from PyQt5.QtGui import QImage, QPixmap

from .sdk_camera_thread import SDKCameraThread

log = logging.getLogger(__name__)


class GLCameraView(QGraphicsView):
    """
    A QGraphicsView that uses QOpenGLWidget viewport for GPU-accelerated rendering,
    and auto-scales the scene to keep the full pixmap visible.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        scene = QGraphicsScene(self)
        self.setScene(scene)
        self._item = QGraphicsPixmapItem()
        scene.addItem(self._item)

        # Use OpenGL for smoother updates
        self.setViewport(QOpenGLWidget())
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setAlignment(Qt.AlignCenter)

    def update_frame(self, qimg: QImage):
        pix = QPixmap.fromImage(qimg)
        self._item.setPixmap(pix)
        # fit the new pixmap into view, keep aspect ratio
        self.fitInView(self._item, Qt.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # on resize, refit whatever pixmap we have
        self.fitInView(self._item, Qt.KeepAspectRatio)


class QtCameraWidget(QWidget):
    """
    Displays live camera feed via SDKCameraThread using OpenGL for performance.
    Manages camera selection, optional software ROI cropping, and resets.
    """

    frame_ready = pyqtSignal(QImage, object)
    camera_resolutions_updated = pyqtSignal(list)
    camera_properties_updated = pyqtSignal(dict)
    camera_error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)

        # full-frame by default (None means "use full sensor")
        self.current_target_fps = 20.0
        self.current_width = None
        self.current_height = None
        self.current_pixel_format = "Mono8"
        self._software_roi = QRectF(0, 0, 0, 0)

        self._camera_thread = None
        self._active_device_info: ic4.DeviceInfo = None

        self._setup_debounce_timers()

        # build UI
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
        if not self._camera_thread:
            return
        thread = self._camera_thread
        self._camera_thread = None

        if thread.isRunning():
            thread.request_stop()
            if not thread.wait(3000):
                thread.terminate()

        try:
            thread.frame_ready.disconnect(self._on_sdk_frame_received)
            thread.camera_error.disconnect(self.camera_error.emit)
            thread.camera_resolutions_available.disconnect(
                self.camera_resolutions_updated.emit
            )
            thread.camera_properties_updated.disconnect(
                self.camera_properties_updated.emit
            )
        except Exception:
            pass

        thread.deleteLater()

    @pyqtSlot(ic4.DeviceInfo)
    def set_active_camera_device(self, device_info: ic4.DeviceInfo = None):
        """Switch to a new camera (or clear)."""
        self._cleanup_camera_thread()
        self._active_device_info = device_info
        if device_info:
            self._start_new_camera_thread()

    def _start_new_camera_thread(self):
        if not self._active_device_info:
            return

        # instantiate thread with optional width/height (None→full)
        self._camera_thread = SDKCameraThread(
            device_info=self._active_device_info,
            target_fps=self.current_target_fps,
            desired_width=self.current_width,
            desired_height=self.current_height,
            desired_pixel_format=self.current_pixel_format,
            parent=self,
        )

        # wire up signals
        self._camera_thread.frame_ready.connect(self._on_sdk_frame_received)
        self._camera_thread.camera_error.connect(self.camera_error.emit)
        self._camera_thread.camera_resolutions_available.connect(
            self.camera_resolutions_updated.emit
        )
        self._camera_thread.camera_properties_updated.connect(
            self.camera_properties_updated.emit
        )

        self._camera_thread.start()

    @pyqtSlot(str)
    def set_active_resolution_str(self, resolution_str: str):
        """Parses 'WxH' and restarts thread with that ROI size."""
        if "x" not in resolution_str:
            return
        w_s, rest = resolution_str.split("x", 1)
        try:
            w = int(w_s)
            h = int(rest.split()[0])
        except ValueError:
            return

        # only restart if truly changed
        if (w, h) != (self.current_width, self.current_height):
            self.current_width, self.current_height = w, h
            self._software_roi = QRectF(0, 0, 0, 0)
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

    def _apply_pending_exposure(self):
        if self._camera_thread and self._exp_pending is not None:
            # force manual
            self._camera_thread.update_auto_exposure(False)
            self._camera_thread.update_exposure(self._exp_pending)
        self._exp_pending = None

    def _apply_pending_gain(self):
        if self._camera_thread and self._gain_pending is not None:
            self._camera_thread.update_gain(self._gain_pending)
        self._gain_pending = None

    @pyqtSlot(int, int, int, int)
    def set_software_roi(self, x: int, y: int, w: int, h: int):
        """
        Defines a cropping rectangle (in sensor coordinates) that
        we apply on the QImage before display.
        """
        self._software_roi = QRectF(x, y, w, h)

    @pyqtSlot()
    def reset_roi_to_default(self):
        """Clear any software ROI and go back to full-sensor capture."""
        self.current_width = None
        self.current_height = None
        self._software_roi = QRectF(0, 0, 0, 0)
        self._cleanup_camera_thread()
        self._start_new_camera_thread()

    @pyqtSlot(QImage, object)
    def _on_sdk_frame_received(self, qimg: QImage, frame_data: object):
        if qimg.isNull():
            return

        # apply software ROI cropping if requested
        roi = self._software_roi
        if roi.width() > 0 and roi.height() > 0:
            cropped = qimg.copy(
                int(roi.x()), int(roi.y()), int(roi.width()), int(roi.height())
            )
        else:
            cropped = qimg

        # push to viewfinder & emit outwards
        self.viewfinder.update_frame(cropped)
        self.frame_ready.emit(cropped, frame_data)

    def current_camera_is_active(self) -> bool:
        return bool(self._camera_thread and self._camera_thread.isRunning())
