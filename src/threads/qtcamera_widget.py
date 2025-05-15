# threads/qtcamera_widget.py
import logging
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtMultimedia import (
    QCamera,
    QCameraInfo,
    QVideoProbe,
    QVideoFrame,
    QAbstractVideoBuffer,
    QCameraViewfinderSettings,
    QMultimedia # For QCamera.Error enum
)
from PyQt5.QtMultimediaWidgets import QCameraViewfinder
from PyQt5 import QtCore
from PyQt5.QtCore import pyqtSignal, Qt, QSize, QRectF
from PyQt5.QtGui import QImage, QPainter, QFont, QColor # **** ADDED QColor ****

log = logging.getLogger(__name__)

class QtCameraWidget(QWidget):
    frame_ready = pyqtSignal(QImage, object)
    camera_error = pyqtSignal(str, int)
    camera_resolutions_updated = pyqtSignal(list)

    def __init__(self, camera_id=-1, parent=None):
        super().__init__(parent)
        self.camera_id = camera_id
        self.camera = None
        self.probe = None
        self.viewfinder = None
        self.current_qimage = None
        self.active_resolution = None
        self._error_message = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        self.viewfinder = QCameraViewfinder(self)
        layout.addWidget(self.viewfinder)
        self.viewfinder.setMinimumSize(320, 240)
        self.setMinimumSize(320, 240)

        if self.camera_id != -1:
            self._setup_camera_device()
        else:
            self._show_error_message("No camera selected.")

    def _setup_camera_device(self):
        self.stop_camera_resources()
        available_cameras = QCameraInfo.availableCameras()
        if not available_cameras:
            log.error("No cameras available."); self._show_error_message("No cameras available.")
            self.camera_error.emit("No cameras available.", self.camera_id); return None
        selected_camera_info = None
        if 0 <= self.camera_id < len(available_cameras):
            selected_camera_info = available_cameras[self.camera_id]
        else:
            log.warning(f"Cam ID {self.camera_id} invalid. Using default.")
            selected_camera_info = QCameraInfo.defaultCamera()
            if selected_camera_info.isNull():
                log.error("No default camera."); self._show_error_message("No default camera.")
                self.camera_error.emit("No default camera found.", -1); return None
            for i, cam_info_iter in enumerate(available_cameras):
                if cam_info_iter == selected_camera_info: self.camera_id = i; break
        log.info(f"Initializing camera: {selected_camera_info.description()} (ID: {self.camera_id})")
        try:
            self.camera = QCamera(selected_camera_info)
            self.camera.setViewfinder(self.viewfinder)
            self.camera.error.connect(self._handle_camera_error)
            self._apply_camera_settings()
            self.probe = QVideoProbe(self)
            if not self.probe.setSource(self.camera):
                 log.error(f"Probe connect failed: Cam {self.camera_id}.")
                 self._show_error_message(f"Probe error: Cam {self.camera_id}.")
                 self.camera_error.emit(f"Probe error", self.camera_id)
                 if self.camera: self.camera.unload(); self.camera = None; return None
            self.probe.videoFrameProbed.connect(self._on_frame)
            self.camera.start()
            if self.camera.state() == QtCore.QCamera.ActiveState: # Using QtCore.QCamera
                log.info(f"Camera {self.camera_id} started."); self._show_error_message(None)
                self._update_resolution_list()
            else: log.warning(f"Cam {self.camera_id} not active. State: {self.camera.state()}")
        except Exception as e:
            log.error(f"Cam setup exception ID {self.camera_id}: {e}", exc_info=True)
            self._show_error_message(f"Init Error: Cam {self.camera_id}")
            self.camera_error.emit(f"Exception: {str(e)}", self.camera_id)
            if self.camera: self.camera.unload(); self.camera = None
        return self.camera

    def _on_frame(self, frame: QVideoFrame): # Keep as is from previous correct version
        if not frame.isValid() or not self.camera: return
        try:
            video_frame_clone = QVideoFrame(frame)
            if video_frame_clone.map(QAbstractVideoBuffer.ReadOnly):
                image_format = QVideoFrame.imageFormatFromPixelFormat(video_frame_clone.pixelFormat())
                image = QImage(video_frame_clone.bits(), video_frame_clone.width(), video_frame_clone.height(), video_frame_clone.bytesPerLine(), image_format)
                if image.isNull(): log.warning(f"QImage null. Format: {image_format}, PixelFormat: {video_frame_clone.pixelFormat()}"); video_frame_clone.unmap(); return
                self.current_qimage = image.copy(); video_frame_clone.unmap()
                if self.current_qimage and not self.current_qimage.isNull(): self.frame_ready.emit(self.current_qimage, None)
            else: log.warning(f"Failed to map video frame for camera {self.camera_id}"); self.current_qimage = None
        except Exception as e: log.error(f"Error processing frame: {e}", exc_info=True); self.current_qimage = None


    def _apply_camera_settings(self): # Keep as is
        if not self.camera: return
        if self.active_resolution and not self.active_resolution.isEmpty():
            settings = QCameraViewfinderSettings()
            supported_resolutions = self.camera.supportedViewfinderResolutions(settings)
            if self.active_resolution in supported_resolutions:
                settings.setResolution(self.active_resolution); self.camera.setViewfinderSettings(settings)
                log.info(f"Applied res {self.active_resolution.width()}x{self.active_resolution.height()} to cam {self.camera_id}")
            else: log.warning(f"Res {self.active_resolution} not supported. Camera using default.")
            
    def _update_resolution_list(self): # Keep as is
        if self.camera:
            settings = QCameraViewfinderSettings()
            try:
                resolutions = self.camera.supportedViewfinderResolutions(settings)
                res_str_list = [f"{res.width()}x{res.height()}" for res in resolutions if not res.isEmpty()]
                self.camera_resolutions_updated.emit(res_str_list)
            except Exception as e: log.error(f"Could not get resolutions for cam {self.camera_id}: {e}"); self.camera_resolutions_updated.emit([])

    def set_active_camera(self, camera_id: int): # Keep as is
        if self.camera and self.camera_id == camera_id and self.camera.state() == QtCore.QCamera.ActiveState: # Use QtCore.QCamera
            log.info(f"Camera {camera_id} already active."); self._update_resolution_list(); return self.camera
        self.camera_id = camera_id; return self._setup_camera_device()

    def set_active_resolution(self, width: int, height: int): # Keep as is
        new_res = QSize(width, height)
        if self.active_resolution != new_res:
            self.active_resolution = new_res; log.info(f"Res preference change: {width}x{height}. Re-init cam.")
            self._setup_camera_device()

    def stop_camera_resources(self): # Keep as is
        log.debug(f"Stopping camera resources for camera ID: {self.camera_id}")
        if self.camera:
            if self.camera.state() == QtCore.QCamera.ActiveState: # Use QtCore.QCamera
                self.camera.stop(); log.info(f"Camera (ID: {self.camera_id}) stopped.")
            self.camera.unload(); self.camera = None
        if self.probe:
            try: self.probe.videoFrameProbed.disconnect(self._on_frame) # Try to disconnect
            except TypeError: pass # Slot not connected or already disconnected
            self.probe.setSource(None); self.probe = None
        self.current_qimage = None

    def _handle_camera_error(self, error_code: QCamera.Error): # Keep as is
        if self.camera:
            error_string = self.camera.errorString()
            log.error(f"Camera {self.camera_id} error: {error_code} - {error_string}")
            self._show_error_message(f"Cam Error: {error_string[:40]}...")
            self.camera_error.emit(error_string, self.camera_id)

    def _show_error_message(self, message): # Keep as is
        self._error_message = message; self.update()

    def paintEvent(self, event): # Keep as is
        super().paintEvent(event)
        if self._error_message:
            painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
            font = QFont("Arial", 12); font.setBold(True); painter.setFont(font)
            text_rect = self.rect().adjusted(10, 10, -10, -10)
            bg_color = QColor(0, 0, 0, 180); painter.fillRect(text_rect, bg_color) # QColor is now imported
            painter.setPen(QtCore.Qt.white); # Use QtCore.Qt
            painter.drawText(text_rect, int(QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap), self._error_message) # Use int() for flags
            painter.end()

    def get_current_resolution(self) -> QSize | None: # Keep as is
        if self.camera and self.camera.state() == QtCore.QCamera.ActiveState: # Use QtCore.QCamera
            vf_settings = self.camera.viewfinderSettings()
            if not vf_settings.isNull() and not vf_settings.resolution().isEmpty(): return vf_settings.resolution()
        return self.active_resolution