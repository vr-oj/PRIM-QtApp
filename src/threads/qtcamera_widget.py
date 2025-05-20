import logging
import imagingcontrol4 as ic4  # For ic4.DeviceInfo
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy
from PyQt5.QtCore import pyqtSignal, Qt, pyqtSlot, QTimer, QSize
from PyQt5.QtGui import QImage, QPixmap, QFont

from .sdk_camera_thread import SDKCameraThread

log = logging.getLogger(__name__)


class QtCameraWidget(QWidget):
    """
    Displays live camera feed via SDKCameraThread.
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
        self.current_width = 640  # Default desired width
        self.current_height = 480  # Default desired height
        self.current_pixel_format = "Mono 8"  # Target this for QImage.Format_Grayscale8

        # ROI state - (x, y, w, h), (0,0,0,0) means full frame or camera default
        self._current_roi = (0, 0, 0, 0)

        self._camera_thread = None
        self._last_pixmap = None
        self._last_view_size = None
        self._last_scaled = None
        self._active_device_info: ic4.DeviceInfo = None  # Store TIS DeviceInfo object

        # --- new: debounce timers & pending values for exposure/gain ---
        self._exp_pending = None
        self._gain_pending = None

        self._exp_timer = QTimer(self)
        self._exp_timer.setSingleShot(True)
        self._exp_timer.setInterval(100)  # 100 ms debounce
        self._exp_timer.timeout.connect(self._apply_pending_exposure)

        self._gain_timer = QTimer(self)
        self._gain_timer.setSingleShot(True)
        self._gain_timer.setInterval(100)
        self._gain_timer.timeout.connect(self._apply_pending_gain)
        # ----------------------------------------------------------------

        # viewfinder
        self.viewfinder = QLabel("No Camera Selected", self)
        self.viewfinder.setAlignment(Qt.AlignCenter)
        self.viewfinder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        font = QFont()
        font.setPointSize(12)
        self.viewfinder.setFont(font)
        self.viewfinder.setStyleSheet(
            "QLabel { background-color : black; color : white; }"
        )
        # let Qt scale the content efficiently
        self.viewfinder.setScaledContents(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.viewfinder)
        self.setLayout(layout)

    def _cleanup_camera_thread(self):
        log.debug("Attempting to cleanup existing camera thread...")
        if self._camera_thread:
            thread_to_clean = self._camera_thread
            self._camera_thread = None  # Dereference early

            if thread_to_clean.isRunning():
                log.info(
                    f"Stopping camera thread ({thread_to_clean.device_info.model_name if thread_to_clean.device_info else 'N/A'})..."
                )
                thread_to_clean.request_stop()
                if not thread_to_clean.wait(3000):  # Wait up to 3s
                    log.warning("Camera thread did not stop gracefully, terminating.")
                    thread_to_clean.terminate()
                else:
                    log.info("Camera thread stopped gracefully.")

            # Disconnect old signals
            try:
                thread_to_clean.frame_ready.disconnect(self._on_sdk_frame_received)
                thread_to_clean.camera_error.disconnect(
                    self._on_camera_thread_error_received
                )
                thread_to_clean.camera_resolutions_available.disconnect(
                    self.camera_resolutions_updated
                )
                thread_to_clean.camera_properties_updated.disconnect(
                    self.camera_properties_updated
                )
            except Exception:
                pass

            thread_to_clean.deleteLater()
            log.debug("Old camera thread scheduled for deletion.")
        else:
            log.debug("No active camera thread to cleanup.")

    @pyqtSlot(ic4.DeviceInfo)
    def set_active_camera_device(self, device_info: ic4.DeviceInfo = None):
        log.info(
            f"QtCameraWidget: Set active camera to: {device_info.model_name if device_info else 'None'}"
        )
        self._cleanup_camera_thread()
        self._active_device_info = device_info
        self._last_pixmap = None

        if self._active_device_info is None:
            self.viewfinder.setText("No Camera Selected")
            self._update_viewfinder_display()
            self.camera_resolutions_updated.emit([])
            self.camera_properties_updated.emit({})
            return

        self.viewfinder.setText(
            f"Connecting to {self._active_device_info.model_name}..."
        )
        self._start_new_camera_thread()

    def _start_new_camera_thread(self):
        if self._camera_thread:
            log.warning("Cleaning up stray camera thread before starting a new one.")
            self._cleanup_camera_thread()

        if not self._active_device_info:
            self.viewfinder.setText("No Camera Selected")
            return

        log.info(
            f"Starting new SDKCameraThread for {self._active_device_info.model_name} with WxH: {self.current_width}x{self.current_height}"
        )
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
        self._camera_thread.camera_error.connect(self._on_camera_thread_error_received)
        self._camera_thread.camera_resolutions_available.connect(
            self.camera_resolutions_updated
        )
        self._camera_thread.camera_properties_updated.connect(
            self.camera_properties_updated
        )
        self._camera_thread.finished.connect(self._on_camera_thread_finished)

        self._camera_thread.start()
        log.info(
            f"SDKCameraThread for {self._active_device_info.model_name} initiated."
        )

    @pyqtSlot(str)
    def set_active_resolution_str(self, resolution_str: str):
        if not resolution_str or "x" not in resolution_str:
            log.warning(f"Invalid resolution string: {resolution_str}")
            return

        try:
            w_str, h_rest = resolution_str.split("x", 1)
            h_str = h_rest.split(" ")[0]
            w, h = int(w_str), int(h_str)

            log.info(f"QtCameraWidget: Set active resolution to W:{w}, H:{h}")
            if (w, h) != (self.current_width, self.current_height):
                self.current_width, self.current_height = w, h
                if self._active_device_info:
                    log.info("Resolution changed, restarting camera thread.")
                    self._cleanup_camera_thread()
                    self._start_new_camera_thread()
        except ValueError:
            log.error(f"Could not parse resolution string: {resolution_str}")

    # ... rest of the class unchanged ...

    def _update_viewfinder_display(self):
        if self._last_pixmap and not self._last_pixmap.isNull():
            size = self.viewfinder.size()
            if size != self._last_view_size:
                self._last_view_size = QSize(size)
                self._last_scaled = self._last_pixmap.scaled(
                    size,
                    Qt.KeepAspectRatio,
                    Qt.FastTransformation,
                )
            if self._last_scaled:
                self.viewfinder.setPixmap(self._last_scaled)
        elif not self.viewfinder.text():
            self.viewfinder.setPixmap(QPixmap())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_viewfinder_display()

    def closeEvent(self, event):
        log.info("QtCameraWidget: closeEvent, cleaning up camera thread.")
        self._cleanup_camera_thread()
        super().closeEvent(event)

    def current_camera_is_active(self) -> bool:
        return bool(self._camera_thread and self._camera_thread.isRunning())
