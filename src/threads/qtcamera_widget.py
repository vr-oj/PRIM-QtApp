# qtcamera_widget.py
import logging
import imagingcontrol4 as ic4  # For ic4.DeviceInfo
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from PyQt5.QtCore import pyqtSignal, pyqtSlot, QTimer
from PyQt5.QtGui import QImage

from .sdk_camera_thread import SDKCameraThread
from .gl_viewfinder import GLViewfinder

log = logging.getLogger(__name__)


class QtCameraWidget(QWidget):
    """
    Displays live camera feed via SDKCameraThread using an OpenGL-based viewfinder.
    Manages camera selection, resolution, and basic properties.
    """

    # Emits a QImage and raw frame data for recording
    frame_ready = pyqtSignal(QImage, object)
    # Emits list of resolution strings
    camera_resolutions_updated = pyqtSignal(list)
    # Emits dict of camera properties
    camera_properties_updated = pyqtSignal(dict)
    # Emits error message and code
    camera_error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)

        # Default parameters
        self.current_target_fps = 20.0
        self.current_width = 640
        self.current_height = 480
        self.current_pixel_format = "Mono 8"
        self._current_roi = (0, 0, 0, 0)

        self._camera_thread = None
        self._active_device_info: ic4.DeviceInfo = None

        # Debounce timers for exposure/gain
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

        # OpenGL-based viewfinder widget
        self.viewfinder = GLViewfinder(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.viewfinder)
        self.setLayout(layout)

    def _cleanup_camera_thread(self):
        log.debug("Cleaning up existing camera thread...")
        if self._camera_thread:
            old = self._camera_thread
            self._camera_thread = None
            if old.isRunning():
                log.info("Stopping camera thread...")
                old.request_stop()
                if not old.wait(3000):
                    log.warning("Camera thread did not stop gracefully; terminating.")
                    old.terminate()
            try:
                old.frame_ready.disconnect(self._on_sdk_frame_received)
                old.camera_error.disconnect(self._on_camera_thread_error_received)
                old.camera_resolutions_available.disconnect(
                    self.camera_resolutions_updated
                )
                old.camera_properties_updated.disconnect(self.camera_properties_updated)
            except Exception:
                pass
            old.deleteLater()

    @pyqtSlot(ic4.DeviceInfo)
    def set_active_camera_device(self, device_info: ic4.DeviceInfo = None):
        log.info(
            f"Setting active camera: {device_info.model_name if device_info else 'None'}"
        )
        self._cleanup_camera_thread()
        self._active_device_info = device_info
        self.camera_resolutions_updated.emit([])
        self.camera_properties_updated.emit({})
        if not device_info:
            return
        self._start_new_camera_thread()

    def _start_new_camera_thread(self):
        if not self._active_device_info:
            return
        log.info(f"Starting SDKCameraThread for {self._active_device_info.model_name}")
        self._camera_thread = SDKCameraThread(
            device_info=self._active_device_info,
            target_fps=self.current_target_fps,
            parent=self,
        )
        # Wire signals
        self._camera_thread.frame_ready.connect(self._on_sdk_frame_received)
        self._camera_thread.camera_error.connect(self._on_camera_thread_error_received)
        self._camera_thread.camera_resolutions_available.connect(
            self.camera_resolutions_updated
        )
        self._camera_thread.camera_properties_updated.connect(
            self.camera_properties_updated
        )
        self._camera_thread.finished.connect(self._on_camera_thread_finished)
        self._camera_thread.start()

    @pyqtSlot(str)
    def set_active_resolution_str(self, resolution_str: str):
        if not resolution_str or "x" not in resolution_str:
            log.warning(f"Invalid resolution string: {resolution_str}")
            return
        try:
            w_str, h_rest = resolution_str.split("x", 1)
            h_str = h_rest.split(" ")[0]
            w, h = int(w_str), int(h_str)
            log.info(f"Setting resolution to {w}x{h}")
            if (w, h) != (self.current_width, self.current_height):
                self.current_width, self.current_height = w, h
                if self._active_device_info:
                    self._cleanup_camera_thread()
                    self._start_new_camera_thread()
        except ValueError:
            log.error(f"Could not parse resolution string: {resolution_str}")

    @pyqtSlot(int)
    def set_exposure(self, exposure_us: int):
        log.debug(f"Queued exposure: {exposure_us}")
        self._exp_pending = exposure_us
        self._exp_timer.start()

    @pyqtSlot(float)
    def set_gain(self, gain_db: float):
        log.debug(f"Queued gain: {gain_db}")
        self._gain_pending = gain_db
        self._gain_timer.start()

    @pyqtSlot(bool)
    def set_auto_exposure(self, enable_auto: bool):
        log.debug(f"Auto-exposure: {enable_auto}")
        if self._camera_thread and self._camera_thread.isRunning():
            self._camera_thread.update_auto_exposure(enable_auto)

    @pyqtSlot()
    def _apply_pending_exposure(self):
        """Apply debounced exposure setting."""
        if self._camera_thread and self._exp_pending is not None:
            self._camera_thread.update_auto_exposure(False)
            self._camera_thread.update_exposure(self._exp_pending)
        self._exp_pending = None

    @pyqtSlot()
    def _apply_pending_gain(self):
        """Apply debounced gain setting."""
        if self._camera_thread and self._gain_pending is not None:
            self._camera_thread.update_gain(self._gain_pending)
        self._gain_pending = None

    @pyqtSlot(int, int, int, int)
    def set_software_roi(self, x: int, y: int, w: int, h: int):
        log.debug(f"ROI: {x},{y},{w},{h}")
        self._current_roi = (x, y, w, h)
        if self._camera_thread and self._camera_thread.isRunning():
            self._camera_thread.update_roi(x, y, w, h)

    @pyqtSlot(QImage, object)
    def _on_sdk_frame_received(self, qimg: QImage, frame_data: object):
        """Handle new frames: render in GLViewfinder and emit for recording."""
        if qimg and not qimg.isNull():
            self.viewfinder.update_frame(qimg)
            self.frame_ready.emit(qimg, frame_data)
        else:
            log.warning("Received null frame from camera thread.")

    @pyqtSlot(str, str)
    def _on_camera_thread_error_received(self, message: str, code: str):
        log.error(f"Camera error: {message} (Code {code})")
        self.camera_error.emit(message, code)

    @pyqtSlot()
    def _on_camera_thread_finished(self):
        log.info("Camera thread finished.")

    def current_camera_is_active(self) -> bool:
        """Return True if the SDK camera thread is alive and running."""
        return bool(self._camera_thread and self._camera_thread.isRunning())
