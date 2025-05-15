import logging
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtMultimedia import (
    QCamera, QCameraInfo, QVideoProbe, QVideoFrame, QAbstractVideoBuffer,
    QCameraViewfinderSettings
)
from PyQt5.QtMultimediaWidgets import QCameraViewfinder
from PyQt5 import QtCore
from PyQt5.QtCore import pyqtSignal, Qt, QSize, QRectF
from PyQt5.QtGui import QImage, QPainter, QFont, QColor

log = logging.getLogger(__name__)

class QtCameraWidget(QWidget):
    frame_ready = pyqtSignal(QImage, object)
    camera_error = pyqtSignal(str, int)
    camera_resolutions_updated = pyqtSignal(list)

    def __init__(self, camera_id=-1, parent=None):
        super().__init__(parent)
        self.camera_id = camera_id
        self.camera: QCamera | None = None # Type hint
        self.probe: QVideoProbe | None = None
        self.viewfinder: QCameraViewfinder | None = None
        self.current_qimage: QImage | None = None
        self.active_resolution: QSize | None = None
        self._error_message: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        self.viewfinder = QCameraViewfinder(self)
        layout.addWidget(self.viewfinder)
        self.viewfinder.setMinimumSize(320, 240)
        self.setMinimumSize(320, 240)

        if self.camera_id != -1:
            self._setup_camera_device()
        else:
            self._show_error_message("No camera selected (Hint: Pick from top panel).")

    def _setup_camera_device(self):
        self.stop_camera_resources()
        available_cameras = QCameraInfo.availableCameras()
        if not available_cameras:
            log.error("No cameras available via QCameraInfo.")
            self._show_error_message("No Qt cameras found.")
            self.camera_error.emit("No Qt cameras available.", self.camera_id)
            return None

        selected_camera_info = None
        if 0 <= self.camera_id < len(available_cameras):
            selected_camera_info = available_cameras[self.camera_id]
        else:
            log.warning(f"Camera ID {self.camera_id} invalid. Trying default.")
            selected_camera_info = QCameraInfo.defaultCamera()
            if selected_camera_info.isNull():
                log.error("No default Qt camera found."); self._show_error_message("No default camera.")
                self.camera_error.emit("No default Qt camera.", -1); return None
            for i, ci in enumerate(available_cameras):
                if ci == selected_camera_info: self.camera_id = i; break
        
        if selected_camera_info.isNull(): # Double check
             log.error("Selected camera_info is null before QCamera creation.")
             self._show_error_message("Camera selection failed.")
             return None

        log.info(f"Initializing QtCamera: {selected_camera_info.description()} (ID: {self.camera_id})")
        try:
            self.camera = QCamera(selected_camera_info)
            self.camera.setViewfinder(self.viewfinder)
            self.camera.error.connect(self._handle_camera_error)
            self._apply_camera_settings()
            self.probe = QVideoProbe(self)
            if not self.probe.setSource(self.camera):
                 log.error(f"Video probe connect failed: Cam {self.camera_id}.")
                 self._show_error_message(f"Probe error: Cam {self.camera_id}.")
                 self.camera_error.emit(f"Probe error", self.camera_id)
                 if self.camera: self.camera.unload(); self.camera = None; return None
            self.probe.videoFrameProbed.connect(self._on_frame)
            self.camera.start()
            # Check state after attempting start
            if self.camera.state() == QCamera.ActiveState: # Use QCamera directly
                log.info(f"Camera {self.camera_id} started successfully.")
                self._show_error_message(None) 
                self._update_resolution_list()
            else:
                 log.warning(f"Camera {self.camera_id} did not reach active state. State: {self.camera.state()}. Error: {self.camera.errorString()}")
                 # Error message might have been set by _handle_camera_error
                 if not self._error_message: # If no specific error was caught by the signal
                    self._show_error_message(f"Cam {self.camera_id} failed to start.")


        except Exception as e:
            log.error(f"Cam setup exception ID {self.camera_id}: {e}", exc_info=True)
            self._show_error_message(f"Init Error: Cam {self.camera_id}")
            self.camera_error.emit(f"Exception: {str(e)}", self.camera_id)
            if self.camera: self.camera.unload(); self.camera = None
        return self.camera

    def _on_frame(self, frame: QVideoFrame):
        if not frame.isValid() or not self.camera: return
        try:
            video_frame_clone = QVideoFrame(frame)
            if video_frame_clone.map(QAbstractVideoBuffer.ReadOnly):
                image_format = QVideoFrame.imageFormatFromPixelFormat(video_frame_clone.pixelFormat())
                
                image = QImage(video_frame_clone.bits(), video_frame_clone.width(), 
                               video_frame_clone.height(), video_frame_clone.bytesPerLine(), image_format)
                
                if image.isNull(): # Could be due to unsupported format
                    log.warning(f"QImage created is null. Original format: {video_frame_clone.pixelFormat()}, "
                                f"QImage mapped format: {image_format}. Attempting ARGB32 fallback.")
                    # Attempt to create QImage with a common format directly from bits if initial format is invalid
                    # This is a guess and might not work for all "Unsupported media type" errors
                    # It assumes the bits can be interpreted as ARGB32.
                    if image_format == QImage.Format_Invalid:
                        # Create a new QImage assuming ARGB32, then convert
                        # This is often a last resort as it assumes a specific underlying byte order.
                        raw_bits = video_frame_clone.bits()
                        # Ensure buffer size matches expected size
                        expected_size = video_frame_clone.width() * video_frame_clone.height() * 4 # 4 bytes for ARGB32
                        if raw_bits.size() >= expected_size :
                            temp_image = QImage(raw_bits, video_frame_clone.width(), video_frame_clone.height(), QImage.Format_ARGB32_Premultiplied)
                            self.current_qimage = temp_image.convertToFormat(QImage.Format_RGB888).copy()
                            if self.current_qimage.isNull():
                                log.error(f"Fallback frame conversion to RGB888 failed for cam {self.camera_id}")
                                self.current_qimage = None
                        else:
                            log.error(f"Buffer size mismatch for ARGB32 fallback. Expected {expected_size}, got {raw_bits.size()}")
                            self.current_qimage = None
                    else: # image_format was valid but QImage ended up null
                        self.current_qimage = None

                else: # image was created successfully with the detected format
                    self.current_qimage = image.copy()

                video_frame_clone.unmap()

                if self.current_qimage and not self.current_qimage.isNull():
                    self.frame_ready.emit(self.current_qimage, None)
                # else: (already logged if conversion failed)
            else:
                log.warning(f"Failed to map video frame for camera {self.camera_id}.")
                self.current_qimage = None
        except Exception as e:
            log.error(f"Error processing frame: {e}", exc_info=True); self.current_qimage = None

    def _apply_camera_settings(self):
        if not self.camera: return
        if self.active_resolution and not self.active_resolution.isEmpty():
            settings = self.camera.viewfinderSettings() # Get current (or default) settings
            if not settings.isNull(): # Check if settings object is valid
                supported_resolutions = self.camera.supportedViewfinderResolutions(settings)
                if self.active_resolution in supported_resolutions:
                    settings.setResolution(self.active_resolution)
                    self.camera.setViewfinderSettings(settings)
                    log.info(f"Applied res {self.active_resolution.width()}x{self.active_resolution.height()} to cam {self.camera_id}")
                else: log.warning(f"Res {self.active_resolution} not directly supported. Camera will use a default.")
            else: log.warning("Could not get viewfinder settings to apply resolution.")
            
    def _update_resolution_list(self):
        if self.camera:
            current_settings = self.camera.viewfinderSettings()
            if not current_settings.isNull():
                try:
                    resolutions = self.camera.supportedViewfinderResolutions(current_settings)
                    res_str_list = [f"{res.width()}x{res.height()}" for res in resolutions if not res.isEmpty()]
                    self.camera_resolutions_updated.emit(res_str_list)
                except Exception as e: log.error(f"Could not get resolutions for cam {self.camera_id}: {e}"); self.camera_resolutions_updated.emit([])
            else: log.warning("Cannot get resolutions, viewfinder settings are null."); self.camera_resolutions_updated.emit([])

    def set_active_camera(self, camera_id: int):
        if self.camera and self.camera_id == camera_id and self.camera.state() == QCamera.ActiveState:
            log.info(f"Camera {camera_id} already active."); self._update_resolution_list(); return self.camera
        self.camera_id = camera_id; return self._setup_camera_device()

    def set_active_resolution(self, width: int, height: int):
        new_res = QSize(width, height)
        if self.active_resolution != new_res:
            self.active_resolution = new_res; log.info(f"Res preference: {width}x{height}. Re-init cam.")
            self._setup_camera_device()

    def stop_camera_resources(self):
        log.debug(f"Stopping cam resources for ID: {getattr(self, 'camera_id', 'N/A')}")
        if self.probe:
            self.probe.setSource(None) # Disconnect source first
            try: self.probe.videoFrameProbed.disconnect(self._on_frame)
            except TypeError: pass 
            self.probe = None
        if self.camera:
            if self.camera.state() == QCamera.ActiveState: self.camera.stop() # QCamera.ActiveState
            self.camera.unload(); self.camera = None
        self.current_qimage = None

    def _handle_camera_error(self, error_code: QCamera.Error):
        error_string = "Unknown Camera Error"
        if self.camera: error_string = self.camera.errorString() # Get string if camera obj exists
        log.error(f"Camera {self.camera_id} error: {error_code} - {error_string}")
        self._show_error_message(f"Cam Error: {error_string[:40]}...")
        self.camera_error.emit(error_string, self.camera_id if self.camera_id is not None else -1)

    def _show_error_message(self, message):
        self._error_message = message; self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._error_message:
            painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
            font = QFont("Arial", 10); font.setBold(True); painter.setFont(font)
            text_rect = self.rect().adjusted(5, 5, -5, -5)
            bg_color = QColor(0, 0, 0, 170); painter.fillRect(text_rect.adjusted(-2,-2,2,2), bg_color)
            painter.setPen(QtCore.Qt.white); # Use QtCore.Qt for color constant
            painter.drawText(text_rect, int(QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap), self._error_message)
            # painter.end() is not strictly necessary for QPainter if it's a local variable

    def get_current_resolution(self) -> QSize | None:
        if self.camera and self.camera.state() == QCamera.ActiveState: # Use QCamera.ActiveState
            vf_settings = self.camera.viewfinderSettings()
            if not vf_settings.isNull() and not vf_settings.resolution().isEmpty(): return vf_settings.resolution()
        return self.active_resolution