import logging
import imagingcontrol4 as ic4  # For ic4.DeviceInfo
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy
from PyQt5.QtCore import pyqtSignal, Qt, pyqtSlot, QTimer
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
        self._current_roi = (
            0,
            0,
            0,
            0,
        )  # x, y, w, h (software ROI, TIS properties handle actual ROI)

        self._camera_thread = None
        self._last_pixmap = None
        self._active_device_info: ic4.DeviceInfo = None  # Store TIS DeviceInfo object

        self.viewfinder = QLabel("No Camera Selected", self)
        self.viewfinder.setAlignment(Qt.AlignCenter)
        self.viewfinder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        font = QFont()
        font.setPointSize(12)
        self.viewfinder.setFont(font)
        self.viewfinder.setStyleSheet(
            "QLabel { background-color : black; color : white; }"
        )

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
                    thread_to_clean.terminate()  # Force if necessary
                else:
                    log.info("Camera thread stopped gracefully.")

            # Disconnect signals to prevent old thread from calling slots
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
            except TypeError as e:
                log.debug(
                    f"Error disconnecting signals (might be already disconnected): {e}"
                )
            except Exception as e:
                log.error(f"Unexpected error disconnecting signals: {e}")

            thread_to_clean.deleteLater()  # Schedule for deletion
            log.debug("Old camera thread scheduled for deletion.")
        else:
            log.debug("No active camera thread to cleanup.")

    @pyqtSlot(ic4.DeviceInfo)  # Slot to receive TIS DeviceInfo object
    def set_active_camera_device(self, device_info: ic4.DeviceInfo = None):
        log.info(
            f"QtCameraWidget: Set active camera to: {device_info.model_name if device_info else 'None'}"
        )

        self._cleanup_camera_thread()  # Stop and clean up any existing thread first
        self._active_device_info = device_info
        self._last_pixmap = None  # Clear last frame

        if self._active_device_info is None:
            self.viewfinder.setText("No Camera Selected")
            self._update_viewfinder_display()
            self.camera_resolutions_updated.emit([])  # Clear resolutions
            self.camera_properties_updated.emit({})  # Clear properties
            return

        self.viewfinder.setText(
            f"Connecting to {self._active_device_info.model_name}..."
        )
        self._start_new_camera_thread()

    def _start_new_camera_thread(self):
        if (
            self._camera_thread is not None
        ):  # Should have been cleaned by set_active_camera_device
            log.warning(
                "_start_new_camera_thread called but a thread already exists. Cleaning up again."
            )
            self._cleanup_camera_thread()

        if self._active_device_info is None:
            log.info("No active TIS device, cannot start camera thread.")
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
            parent=self,  # Ensure QObject parentage for thread if needed by Qt's thread management
        )

        # Connect signals from the new thread
        self._camera_thread.frame_ready.connect(self._on_sdk_frame_received)
        self._camera_thread.camera_error.connect(self._on_camera_thread_error_received)
        self._camera_thread.camera_resolutions_available.connect(
            self.camera_resolutions_updated
        )  # Pass through
        self._camera_thread.camera_properties_updated.connect(
            self.camera_properties_updated
        )  # Pass through

        self._camera_thread.finished.connect(
            self._on_camera_thread_finished
        )  # Good for logging

        self._camera_thread.start()
        log.info(
            f"SDKCameraThread for {self._active_device_info.model_name} initiated."
        )

    @pyqtSlot(str)  # Expects "WidthxHeight" string e.g. "1280x720"
    def set_active_resolution_str(self, resolution_str: str):
        if not resolution_str or "x" not in resolution_str:
            log.warning(f"Invalid resolution string: {resolution_str}")
            return

        try:
            w_str, h_str_rest = resolution_str.split("x", 1)
            # h_str might contain pixel format like "720 (Mono 8)"
            h_str = h_str_rest.split(" ")[0]  # Take only the number part for height

            w = int(w_str)
            h = int(h_str)

            log.info(f"QtCameraWidget: Set active resolution to W:{w}, H:{h}")
            if self.current_width != w or self.current_height != h:
                self.current_width = w
                self.current_height = h
                # If a camera is active, restart the thread with new resolution
                if self._active_device_info:
                    log.info("Resolution changed, restarting camera thread.")
                    self._cleanup_camera_thread()
                    # QTimer.singleShot(100, self._start_new_camera_thread) # Short delay to ensure cleanup
                    self._start_new_camera_thread()  # Start immediately
                else:
                    log.info("Resolution set, but no active camera to restart.")
        except ValueError:
            log.error(f"Could not parse resolution string: {resolution_str}")

    @pyqtSlot(int)
    def set_exposure(self, exposure_us: int):
        log.debug(
            f"QtCameraWidget: Queuing exposure change to camera thread: {exposure_us} us"
        )
        if self._camera_thread and self._camera_thread.isRunning():
            self._camera_thread.update_exposure(exposure_us)

    @pyqtSlot(float)  # TIS gain is often float (dB)
    def set_gain(self, gain_db: float):
        log.debug(f"QtCameraWidget: Queuing gain change to camera thread: {gain_db} dB")
        if self._camera_thread and self._camera_thread.isRunning():
            self._camera_thread.update_gain(gain_db)

    @pyqtSlot(bool)
    def set_auto_exposure(self, enable_auto: bool):
        log.debug(
            f"QtCameraWidget: Queuing auto-exposure toggle to camera thread: {enable_auto}"
        )
        if self._camera_thread and self._camera_thread.isRunning():
            self._camera_thread.update_auto_exposure(enable_auto)

    @pyqtSlot(
        int
    )  # Brightness is not a direct TIS param, usually maps to gain or gamma. Ignoring for now.
    def set_brightness(self, value: int):
        log.warning(
            f"QtCameraWidget: set_brightness({value}) called, but not implemented for TIS SDK directly. Consider mapping to Gain or Gamma if available."
        )
        pass

    @pyqtSlot(int, int, int, int)
    def set_software_roi(self, x: int, y: int, w: int, h: int):
        """
        This is a request to set ROI. The SDKCameraThread will attempt to set OffsetX, OffsetY.
        Changes to Width/Height via ROI usually require a stream restart and should be handled
        by set_active_resolution if the actual frame size needs to change.
        """
        log.info(
            f"QtCameraWidget: Queuing ROI to camera thread: x={x}, y={y}, w={w}, h={h}"
        )
        self._current_roi = (x, y, w, h)  # Store intended ROI
        if self._camera_thread and self._camera_thread.isRunning():
            # The camera thread will primarily try to set OffsetX/OffsetY.
            # If w/h are different from current camera w/h, it won't change size on the fly easily.
            # That should be handled by selecting a new resolution that matches the ROI w/h.
            self._camera_thread.update_roi(x, y, w, h)

    @pyqtSlot()
    def reset_roi_to_default(self):
        log.info("QtCameraWidget: Resetting ROI to default (full frame).")
        # This typically means setting offsets to 0. The width/height should revert to
        # the camera's current full resolution for those offsets.
        # We can trigger this by setting ROI with 0,0 for x,y and perhaps 0,0 for w,h
        # if the camera thread understands that as "reset to max".
        # Or, more reliably, restart with default/max width/height.

        # For now, just set offsets to 0 and keep current W/H.
        # A true "reset" might involve querying max width/height and setting that resolution.
        self.set_software_roi(
            0, 0, self.current_width, self.current_height
        )  # Set offset to 0,0 with current W,H
        # The thread might re-evaluate W/H based on this.
        # Or, more simply, just set offsets to 0
        if self._camera_thread and self._camera_thread.isRunning():
            self._camera_thread.update_roi(
                0, 0, 0, 0
            )  # Signal thread to reset offsets. W/H might be ignored or used by thread.

    @pyqtSlot(QImage, object)
    def _on_sdk_frame_received(self, qimg: QImage, frame_data: object):
        if (
            self.viewfinder.text() and not qimg.isNull()
        ):  # Clear "Connecting..." message
            self.viewfinder.setText("")

        if qimg and not qimg.isNull():
            self._last_pixmap = QPixmap.fromImage(qimg)
            self._update_viewfinder_display()
            self.frame_ready.emit(qimg, frame_data)  # Pass along the frame
        else:
            log.warning("Received null QImage from SDK thread.")
            # self.viewfinder.setText("Error: Null frame") # Avoid overwriting other errors

    @pyqtSlot(str, str)
    def _on_camera_thread_error_received(self, message: str, code: str):
        log.error(f"QtCameraWidget received camera error: {message} (Code: {code})")
        # Display a concise error on the viewfinder
        display_message = f"Camera Error ({code})"
        if len(message) < 50:
            display_message = f"Camera Error: {message}"

        self.viewfinder.setText(display_message)
        self._last_pixmap = None  # Clear pixmap on error
        self._update_viewfinder_display()
        self.camera_error.emit(message, code)  # Propagate the error signal

        # Optional: Attempt to cleanup the failed thread
        # if self.sender() == self._camera_thread:
        #    log.info("Cleaning up failed camera thread due to error.")
        #    self._cleanup_camera_thread() # This might be too aggressive if error is recoverable

    @pyqtSlot()
    def _on_camera_thread_finished(self):
        sending_thread = self.sender()
        device_name = "Unknown"
        if isinstance(sending_thread, SDKCameraThread) and sending_thread.device_info:
            device_name = sending_thread.device_info.model_name

        log.info(f"SDKCameraThread for {device_name} has finished.")
        # If the thread that finished is the *current* active one, then nullify it
        if self._camera_thread == sending_thread:
            log.debug(
                f"Current camera thread ({device_name}) is now marked as finished."
            )
            # self._camera_thread = None # No, cleanup should handle this.
            # This slot is just for notification.
            # If it finished unexpectedly (not due to a cleanup call), then show message.
            # However, distinguishing that is tricky here. Best to rely on error signals.

    def _update_viewfinder_display(self):
        if self._last_pixmap and not self._last_pixmap.isNull():
            # Scale pixmap to fit viewfinder, keeping aspect ratio
            scaled_pixmap = self._last_pixmap.scaled(
                self.viewfinder.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.viewfinder.setPixmap(scaled_pixmap)
        elif (
            not self.viewfinder.text()
        ):  # If no text (like error message), and no pixmap
            self.viewfinder.setPixmap(QPixmap())  # Clear stale pixmap
            # self.viewfinder.setText("No Image") # Or set a default text

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_viewfinder_display()  # Re-scale pixmap on resize

    def closeEvent(self, event):
        log.info("QtCameraWidget closeEvent called. Cleaning up camera thread.")
        self._cleanup_camera_thread()
        super().closeEvent(event)

    def current_camera_is_active(self) -> bool:
        return self._camera_thread is not None and self._camera_thread.isRunning()
