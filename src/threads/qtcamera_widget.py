import logging
import imagingcontrol4 as ic4  # For ic4.DeviceInfo
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QSizePolicy
from PyQt5.QtCore import pyqtSignal, Qt, pyqtSlot, QTimer
from PyQt5.QtGui import QImage

from .gl_viewfinder import GLViewfinder
from .sdk_camera_thread import SDKCameraThread

log = logging.getLogger(__name__)


class QtCameraWidget(QWidget):
    """
    Displays live camera feed via SDKCameraThread using an OpenGL viewfinder.
    Manages camera selection, resolution, and basic properties.
    """

    # Signals a copy of the QImage and the original numpy array (if available)
    frame_ready = pyqtSignal(QImage, object)
    # Emits list of strings like "WidthxHeight (PixelFormat)"
    camera_resolutions_updated = pyqtSignal(list)
    # Emits a dictionary of camera properties and their current states/ranges
    camera_properties_updated = pyqtSignal(dict)
    # Emits error message and a string code for the error type
    camera_error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)

        # Default camera parameters (can be overridden by GUI or loaded settings)
        self.current_target_fps = 20.0
        self.current_width = 640
        self.current_height = 480
        self.current_pixel_format = "Mono 8"

        # ROI state - (x, y, w, h), (0,0,0,0) means full frame
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

        # OpenGL viewfinder
        self.viewfinder = GLViewfinder(self)
        self.viewfinder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.viewfinder)
        self.setLayout(layout)

    def _cleanup_camera_thread(self):
        log.debug("Cleaning up existing camera thread…")
        if not self._camera_thread:
            return

        old = self._camera_thread
        self._camera_thread = None

        if old.isRunning():
            old.request_stop()
            if not old.wait(3000):
                log.warning("Thread didn’t stop gracefully; terminating.")
                old.terminate()

        for sig in (
            (old.frame_ready, self._on_sdk_frame_received),
            (old.camera_error, self._on_camera_thread_error_received),
            (old.camera_resolutions_available, self.camera_resolutions_updated),
            (old.camera_properties_updated, self.camera_properties_updated),
        ):
            try:
                sig[0].disconnect(sig[1])
            except Exception:
                pass

        old.deleteLater()

    @pyqtSlot(ic4.DeviceInfo)
    def set_active_camera_device(self, device_info: ic4.DeviceInfo = None):
        log.info(f"Switching to camera: {getattr(device_info, 'model_name', 'None')}")
        self._cleanup_camera_thread()
        self._active_device_info = device_info

        if not device_info:
            self.camera_resolutions_updated.emit([])
            self.camera_properties_updated.emit({})
            return

        self.viewfinder.show_connecting(device_info.model_name)
        self._start_new_camera_thread()

    def _start_new_camera_thread(self):
        if self._camera_thread:
            self._cleanup_camera_thread()

        if not self._active_device_info:
            return

        thread = SDKCameraThread(
            device_info=self._active_device_info,
            target_fps=self.current_target_fps,
            parent=self,
        )
        thread.frame_ready.connect(self._on_sdk_frame_received)
        thread.camera_error.connect(self._on_camera_thread_error_received)
        thread.camera_resolutions_available.connect(self.camera_resolutions_updated)
        thread.camera_properties_updated.connect(self.camera_properties_updated)
        thread.finished.connect(self._on_camera_thread_finished)
        self._camera_thread = thread
        thread.start()

    @pyqtSlot(str)
    def set_active_resolution_str(self, resolution_str: str):
        if "x" not in resolution_str:
            log.warning(f"Bad resolution: {resolution_str}")
            return
        w, h = map(int, resolution_str.split("x")[0:2])
        if (w, h) != (self.current_width, self.current_height):
            self.current_width, self.current_height = w, h
            if self._active_device_info:
                self._cleanup_camera_thread()
                self._start_new_camera_thread()

    # Debounced exposure/gain

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
        if self._exp_pending is not None and self._camera_thread:
            self._camera_thread.update_auto_exposure(False)
            self._camera_thread.update_exposure(self._exp_pending)
        self._exp_pending = None

    @pyqtSlot()
    def _apply_pending_gain(self):
        if self._gain_pending is not None and self._camera_thread:
            self._camera_thread.update_gain(self._gain_pending)
        self._gain_pending = None

    # ROI / brightness (unchanged)
    @pyqtSlot(int, int, int, int)
    def set_software_roi(self, x, y, w, h):
        self._current_roi = (x, y, w, h)
        if self._camera_thread and self._camera_thread.isRunning():
            self._camera_thread.update_roi(x, y, w, h)

    @pyqtSlot()
    def reset_roi_to_default(self):
        self.set_software_roi(0, 0, 0, 0)

    @pyqtSlot(int)
    def set_brightness(self, value: int):
        log.warning("Brightness not implemented.")

    # Frame callbacks

    @pyqtSlot(QImage, object)
    def _on_sdk_frame_received(self, qimg: QImage, frame_data: object):
        if qimg and not qimg.isNull():
            self.viewfinder.update_frame(qimg)
            self.frame_ready.emit(qimg, frame_data)
        else:
            log.warning("Null frame received.")

    @pyqtSlot(str, str)
    def _on_camera_thread_error_received(self, message: str, code: str):
        log.error(f"Camera error [{code}]: {message}")
        self.viewfinder.show_error(message)
        self.camera_error.emit(message, code)

    @pyqtSlot()
    def _on_camera_thread_finished(self):
        log.info("Camera thread finished.")

    def current_camera_is_active(self) -> bool:
        return bool(self._camera_thread and self._camera_thread.isRunning())
