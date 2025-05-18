# src/threads/qtcamera_widget.py

import logging
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy
from PyQt5.QtCore import pyqtSignal, Qt, pyqtSlot, QTimer
from PyQt5.QtGui import QImage, QPixmap, QFont
from .sdk_camera_thread import (
    SDKCameraThread,
)  # Assuming sdk_camera_thread.py is in the same directory

log = logging.getLogger(__name__)


class QtCameraWidget(QWidget):
    """
    Shows a live feed from the SDKCameraThread (scaled in the UI)
    and provides full-resolution frames (QImage and raw numpy array) for recording or processing.
    """

    # Emits: QImage (for UI preview), object (raw numpy array for recording/processing)
    frame_ready = pyqtSignal(QImage, object)
    # Emits: list of resolution strings e.g., ["640x480", "1920x1080"]
    # This would typically be populated after querying camera capabilities.
    camera_resolutions_updated = pyqtSignal(list)
    # Emits: error_message (str), error_code_str (str) - forwarded from SDKCameraThread
    camera_error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # start with a sensible default resolution
        self.default_width = 640
        self.default_height = 480
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Preview label
        self.viewfinder = QLabel(self)
        self.viewfinder.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(12)  # Or adjust as needed
        self.viewfinder.setFont(font)
        self.viewfinder.setScaledContents(False)  # We handle scaling in _update_display
        self.viewfinder.setText("Camera Disconnected")  # Initial text

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.viewfinder)

        self._camera_thread = None
        self._last_pixmap = None  # For displaying scaled images
        self._active_camera_id = -1
        self._active_camera_description = ""

        # Default camera parameters (can be made configurable)
        self.default_exposure_us = 20000
        self.default_target_fps = 20

    def set_active_camera(self, camera_id: int, camera_description: str = ""):
        log.info(
            f"QtCameraWidget: Setting active camera to ID {camera_id} ('{camera_description}')"
        )
        self._active_camera_id = camera_id
        self._active_camera_description = camera_description

        if self._camera_thread is not None and self._camera_thread.isRunning():
            log.info("QtCameraWidget: Stopping existing camera thread...")
            # Disconnect old signals to prevent multiple calls if thread takes time to stop
            try:
                self._camera_thread.frame_ready.disconnect(self._on_sdk_frame_received)
                self._camera_thread.camera_error.disconnect(
                    self._on_camera_thread_error
                )
            except TypeError:  # Raised if signals were not connected
                pass

            self._camera_thread.stop()  # Signal the thread to stop its loop
            # Connect to finished signal for cleanup AFTER it has fully stopped
            self._camera_thread.finished.connect(self._on_camera_thread_object_cleanup)
            # Don't set self._camera_thread to None here yet. Let the finished signal handle it.
        else:
            # If no thread running, proceed to start a new one directly
            self._start_new_camera_thread()

    def _on_camera_thread_object_cleanup(self):
        log.info("QtCameraWidget: _on_camera_thread_object_cleanup called.")
        sender_thread = self.sender()
        if sender_thread:  # Check if sender is valid (it should be the finished thread)
            sender_thread.deleteLater()  # Schedule for deletion

        # If the finished thread was the one we were trying to replace, start the new one.
        # This logic ensures that the old thread fully exits before a new one for the *same*
        # device might be started, preventing resource conflicts if set_active_camera is called rapidly.
        # However, if camera_id is -1 (disconnect), we don't start a new one.
        if (
            self._camera_thread == sender_thread
        ):  # check if it's the current active thread that finished
            self._camera_thread = None
            self._start_new_camera_thread()  # Now attempt to start based on current _active_camera_id

    def _start_new_camera_thread(self):
        # This method is called either directly if no thread was running,
        # or by _on_camera_thread_object_cleanup after the old thread has been dealt with.

        if self._camera_thread is not None:  # Should not happen if logic is correct
            log.warning(
                "QtCameraWidget: Attempted to start a new thread while one was still assigned."
            )
            return

        if self._active_camera_id < 0:  # User selected "No camera" or an error occurred
            self.viewfinder.setText("Camera Disconnected")
            if self._last_pixmap:  # Clear previous image
                self._last_pixmap = None
                self._update_display()
            self.camera_resolutions_updated.emit([])  # Inform no resolutions
            log.info("QtCameraWidget: No camera active or disconnect requested.")
            return

        log.info(
            f"QtCameraWidget: Initializing and starting SDKCameraThread for '{self._active_camera_description}' (ID: {self._active_camera_id})"
        )
        self.viewfinder.setText(f"Connecting to {self._active_camera_description}...")

        # Pass parameters to SDKCameraThread
        self._camera_thread = SDKCameraThread(
            exposure_us=self.default_exposure_us,
            target_fps=self.default_target_fps,
            width=self.default_width,
            height=self.default_height,
            pixel_format=self.default_pixel_format,
            parent=None,
        )
        self._camera_thread.frame_ready.connect(self._on_sdk_frame_received)
        self._camera_thread.camera_error.connect(self._on_camera_thread_error)
        self._camera_thread.camera_resolutions_available.connect(
            self.camera_resolutions_updated
        )
        self._camera_thread.start()  # Start the thread's run() method

    def set_active_resolution(self, width: int, height: int):
        """
        Called when the user selects a new resolution (WxH).
        We update our defaults and restart the camera thread.
        """
        self.default_width = width
        self.default_height = height
        # If a camera is already running, re-set it to restart the thread
        if self._active_camera_id >= 0:
            self.set_active_camera(
                self._active_camera_id, self._active_camera_description
            )

    @pyqtSlot(
        QImage, object
    )  # Receives QImage for preview, object (numpy array) for recording
    def _on_sdk_frame_received(self, preview_qimage: QImage, raw_numpy_frame: object):
        if (
            self.viewfinder.text() != ""
        ):  # Clear "Connecting..." or error messages on first good frame
            self.viewfinder.setText("")

        if preview_qimage and not preview_qimage.isNull():
            self._last_pixmap = QPixmap.fromImage(preview_qimage)
            self._update_display()  # Update the GUI viewfinder

            # Forward both the QImage (for potential other UI uses) and the raw numpy frame
            self.frame_ready.emit(preview_qimage, raw_numpy_frame)
        else:
            log.debug(
                "QtCameraWidget: Received null or invalid QImage in _on_sdk_frame_received."
            )

    @pyqtSlot(str, str)  # Receives error_message (str), error_code_str (str)
    def _on_camera_thread_error(self, error_message: str, error_code_str: str):
        log.error(
            f"QtCameraWidget: Error from SDKCameraThread: '{error_message}' (Code: {error_code_str})"
        )
        self.viewfinder.setText(
            f"Camera Error: {error_message[:60]}{'...' if len(error_message)>60 else ''}"
        )  # Show truncated error
        self.camera_error.emit(
            error_message, error_code_str
        )  # Forward the error to MainWindow

        # If an error occurs, we might want to ensure the thread is cleaned up.
        # The SDKCameraThread itself should try to clean up its IC4 resources.
        # Here, we ensure the Qt thread object is handled.
        if self._camera_thread and self.sender() == self._camera_thread:
            # If thread is still running but emitted a fatal error, ensure it's stopped.
            # This might be redundant if the thread's run() method exits on error.
            self._camera_thread.stop()  # Signal it to stop
            # Consider connecting to finished if not already handled or if stop doesn't guarantee immediate exit.
            # For simplicity, we'll assume the thread stops itself or stop() is effective.
            # self._camera_thread = None # Or better, handle via finished signal with deleteLater

    def _update_display(self):
        if self._last_pixmap and not self._last_pixmap.isNull():
            # Scale pixmap to viewfinder size while keeping aspect ratio
            scaled_pixmap = self._last_pixmap.scaled(
                self.viewfinder.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.viewfinder.setPixmap(scaled_pixmap)
        elif (
            not self.viewfinder.text()
        ):  # If no text (like error/connecting), clear pixmap
            self.viewfinder.setPixmap(QPixmap())  # Clear image

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_display()  # Re-scale pixmap when widget is resized

    def closeEvent(self, event):  # Called when the QWidget is about to be closed
        log.info("QtCameraWidget: closeEvent triggered.")
        if self._camera_thread and self._camera_thread.isRunning():
            log.info("QtCameraWidget: Stopping camera thread in closeEvent...")
            self._camera_thread.stop()
            # Wait for the thread to finish, with a timeout.
            # This is important to ensure resources are released before the application exits,
            # especially if the thread interacts with hardware.
            if not self._camera_thread.wait(3000):  # Wait up to 3 seconds
                log.warning(
                    "QtCameraWidget: SDKCameraThread did not finish gracefully within timeout during closeEvent."
                )
                # self._camera_thread.terminate() # Use terminate() as a last resort if wait fails
            else:
                log.info("QtCameraWidget: SDKCameraThread finished gracefully.")
        self._camera_thread = None  # Clear reference
        super().closeEvent(event)

    # --- Public methods to control camera parameters (examples) ---
    # These would typically be called by MainWindow based on GUI controls

    def set_exposure(self, exposure_us: int):
        if self._camera_thread and self._camera_thread.isRunning():
            # This requires SDKCameraThread to have a method to change exposure dynamically.
            # For now, SDKCameraThread sets exposure on init.
            # To make it dynamic, SDKCameraThread would need a new method and likely a way
            # to safely access its property map (pm) while running.
            log.info(
                f"QtCameraWidget: Request to set exposure to {exposure_us} (not yet implemented in SDK thread dynamically)."
            )
            # Example if SDKCameraThread had a set_exposure method:
            # self._camera_thread.set_exposure(exposure_us)
            self.default_exposure_us = exposure_us  # Store for next thread start
        else:
            self.default_exposure_us = exposure_us
            log.debug(
                f"QtCameraWidget: Exposure set to {exposure_us} (will apply on next camera start)."
            )

    def set_target_fps(self, fps: int):
        if self._camera_thread and self._camera_thread.isRunning():
            log.info(
                f"QtCameraWidget: Request to set FPS to {fps} (not yet implemented in SDK thread dynamically)."
            )
            # Similar to exposure, dynamic FPS change would need SDKCameraThread support.
            self.default_target_fps = fps
        else:
            self.default_target_fps = fps
            log.debug(
                f"QtCameraWidget: Target FPS set to {fps} (will apply on next camera start)."
            )

    # Add methods for other parameters like resolution, ROI if needed.
    # For resolution changes, you'd typically stop the current thread,
    # update desired_width/height in SDKCameraThread (or pass as new params),
    # and then start a new thread instance.
