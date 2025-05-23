# qtcamera_widget.py
import logging
import imagingcontrol4 as ic4  # ic4.DeviceInfo
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import pyqtSignal, pyqtSlot, QTimer, Qt
from PyQt5.QtGui import QImage, QPixmap

from .sdk_camera_thread import SDKCameraThread

log = logging.getLogger(__name__)


class QtCameraWidget(QWidget):
    """
    Displays live camera feed via SDKCameraThread using a QLabel preview.
    Manages camera selection, resolution, and safe shutdown.
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

        # Preview label
        self.viewfinder = QLabel(self)
        self.viewfinder.setAlignment(Qt.AlignCenter)
        self.viewfinder.setScaledContents(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.viewfinder)
        self.setLayout(layout)

        self._camera_thread = None
        self._active_device_info: ic4.DeviceInfo = None

    def closeEvent(self, event):
        """
        Ensure camera is cleanly shutdown when widget is closed.
        """
        self.stop_camera()
        super().closeEvent(event)

    @pyqtSlot()
    def stop_camera(self):
        """
        Stops and cleans up the camera thread, releasing the device safely.
        """
        if self._camera_thread:
            log.info("Stopping camera for safe shutdown...")
            # Request thread stop
            self._camera_thread.request_stop()
            # Wait for thread to finish
            if not self._camera_thread.wait(3000):
                log.warning("Camera thread did not stop, terminating forcefully.")
                self._camera_thread.terminate()
            # Optionally close device if supported
            try:
                if hasattr(self._camera_thread, "close_device"):
                    self._camera_thread.close_device()
            except Exception as e:
                log.warning(f"Error closing device: {e}")

            # Disconnect signals
            try:
                self._camera_thread.frame_ready.disconnect(self.update_frame)
                self._camera_thread.camera_resolutions_available.disconnect(
                    self.camera_resolutions_updated
                )
                self._camera_thread.camera_properties_updated.disconnect(
                    self.camera_properties_updated
                )
                self._camera_thread.error.disconnect(self.camera_error)
            except Exception:
                pass

            # Delete and clear reference
            self._camera_thread.deleteLater()
            self._camera_thread = None

    @pyqtSlot(ic4.DeviceInfo)
    def set_active_camera_device(self, device_info: ic4.DeviceInfo):
        """
        Start or restart the SDKCameraThread and connect signals.
        """
        # Stop existing camera if any
        self.stop_camera()

        self._active_device_info = device_info
        # Create and start new thread
        # Supply your CTI path and pick device_index 0 (or derive from device_info.id_)
        self._camera_thread = HarvesterCameraThread(
            cti_path=r"C:\Program Files\The Imaging Source Europe GmbH\IC4 GenTL Driver for USB3Vision Devices 1.4\bin\ic4-gentl-u3v_x64.cti",
            device_index=0,
            parent=self,
        )
        # Connect frame updates
        self._camera_thread.frame_ready.connect(self.update_frame)
        # Connect other signals
        self._camera_thread.camera_resolutions_available.connect(
            self.camera_resolutions_updated
        )
        self._camera_thread.camera_properties_updated.connect(
            self.camera_properties_updated
        )
        self._camera_thread.error.connect(self.camera_error)

        log.info(f"Starting camera thread for {device_info.model_name}")
        self._camera_thread.start()

    @pyqtSlot(QImage, object)
    def update_frame(self, qimg: QImage, frame_data=None):
        """
        Display incoming frames in QLabel and emit for recording.
        """
        if qimg and not qimg.isNull():
            pix = QPixmap.fromImage(qimg)
            self.viewfinder.setPixmap(pix)
            self.frame_ready.emit(qimg, frame_data)
        else:
            log.warning("Received invalid frame in update_frame")

    def current_camera_is_active(self) -> bool:
        """Check if camera thread is running."""
        return bool(self._camera_thread and self._camera_thread.isRunning())
