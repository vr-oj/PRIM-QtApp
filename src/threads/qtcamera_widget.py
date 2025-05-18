import logging
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy
from PyQt5.QtCore import pyqtSignal, Qt, pyqtSlot
from PyQt5.QtGui import QImage, QPixmap, QFont
from .sdk_camera_thread import SDKCameraThread

log = logging.getLogger(__name__)


class QtCameraWidget(QWidget):
    """
    Displays live camera feed via SDKCameraThread and emits frames.
    """

    frame_ready = pyqtSignal(QImage, object)
    camera_resolutions_updated = pyqtSignal(list)
    camera_error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Default capture parameters
        self.default_width = 640
        self.default_height = 480
        self.default_pixel_format = "Mono8"
        self.default_exposure_us = 20000
        self.default_target_fps = 20
        self.default_gain = 0

        self._camera_thread = None
        self._last_pixmap = None
        self._active_camera_id = -1
        self._active_camera_description = ""

        self.viewfinder = QLabel("Camera Disconnected", self)
        self.viewfinder.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(12)
        self.viewfinder.setFont(font)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.viewfinder)

    def set_active_camera(self, camera_id: int, camera_description: str = ""):
        log.info(f"Setting camera ID {camera_id} ('{camera_description}')")
        self._active_camera_id = camera_id
        self._active_camera_description = camera_description

        if self._camera_thread and self._camera_thread.isRunning():
            try:
                self._camera_thread.frame_ready.disconnect(self._on_sdk_frame_received)
                self._camera_thread.camera_error.disconnect(
                    self._on_camera_thread_error
                )
            except TypeError:
                pass
            self._camera_thread.stop()
            self._camera_thread.finished.connect(self._on_thread_cleanup)
        else:
            self._start_new_camera_thread()

    def _on_thread_cleanup(self):
        sender = self.sender()
        if sender:
            sender.deleteLater()
        if self._camera_thread == sender:
            self._camera_thread = None
            self._start_new_camera_thread()

    def _start_new_camera_thread(self):
        if self._camera_thread:
            return
        if self._active_camera_id < 0:
            self.viewfinder.setText("Camera Disconnected")
            self._last_pixmap = None
            self._update_display()
            self.camera_resolutions_updated.emit([])
            return

        self.viewfinder.setText(f"Connecting to {self._active_camera_description}...")
        thread = SDKCameraThread(
            exposure_us=self.default_exposure_us,
            target_fps=self.default_target_fps,
            width=self.default_width,
            height=self.default_height,
            pixel_format=self.default_pixel_format,
        )
        thread.frame_ready.connect(self._on_sdk_frame_received)
        thread.camera_error.connect(self._on_camera_thread_error)
        thread.camera_resolutions_available.connect(self.camera_resolutions_updated)
        thread.start()
        self._camera_thread = thread

    def set_active_resolution(self, width: int, height: int):
        self.default_width = width
        self.default_height = height
        if self._active_camera_id >= 0:
            self.set_active_camera(
                self._active_camera_id, self._active_camera_description
            )

    def set_exposure(self, exposure_us: int):
        if self._camera_thread and self._camera_thread.isRunning():
            log.info(f"Queuing exposure change: {exposure_us}")
            self._camera_thread.update_exposure(exposure_us)
        else:
            self.default_exposure_us = exposure_us

    def set_gain(self, gain: int):
        if self._camera_thread and self._camera_thread.isRunning():
            log.info(f"Queuing gain change: {gain}")
            self._camera_thread.update_gain(gain)
        else:
            self.default_gain = gain

    @pyqtSlot(QImage, object)
    def _on_sdk_frame_received(self, qimg: QImage, frame: object):
        if self.viewfinder.text():
            self.viewfinder.setText("")
        self._last_pixmap = QPixmap.fromImage(qimg)
        self._update_display()
        self.frame_ready.emit(qimg, frame)

    @pyqtSlot(str, str)
    def _on_camera_thread_error(self, message: str, code: str):
        log.error(f"Camera error: {message} ({code})")
        self.viewfinder.setText(
            f"Camera Error: {message[:60]}{'...' if len(message)>60 else ''}"
        )
        self.camera_error.emit(message, code)
        if self._camera_thread and self.sender() == self._camera_thread:
            self._camera_thread.stop()

    def _update_display(self):
        if self._last_pixmap and not self._last_pixmap.isNull():
            scaled = self._last_pixmap.scaled(
                self.viewfinder.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.viewfinder.setPixmap(scaled)
        else:
            self.viewfinder.setPixmap(QPixmap())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_display()

    def closeEvent(self, event):
        if self._camera_thread and self._camera_thread.isRunning():
            self._camera_thread.stop()
            self._camera_thread.wait(3000)
        self._camera_thread = None
        super().closeEvent(event)
