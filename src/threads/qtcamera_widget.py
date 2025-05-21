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

    # ... existing methods ...

    @pyqtSlot(QImage, object)
    def _on_sdk_frame_received(self, qimg: QImage, frame_data: object):
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
