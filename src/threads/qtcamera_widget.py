import cv2
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import QTimer, pyqtSignal, Qt, QSize # Make sure QSize is imported
from PyQt5.QtGui import QImage, QPixmap
import logging # It's good practice to log errors/info

log = logging.getLogger(__name__) # Add logger

class QtCameraWidget(QWidget):
    frame_ready = pyqtSignal(QImage, object) # QImage for display, object for raw frame (e.g., numpy array)
    camera_error = pyqtSignal(str, int)      # Error message, error code (optional)
    camera_resolutions_updated = pyqtSignal(list) # To emit list of available resolutions as strings

    def __init__(self, camera_id: int = -1, parent=None): # default camera_id can be -1 (no camera)
        super().__init__(parent)
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setText("Camera feed will appear here.") # Placeholder text
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self.label)

        self.cap = None
        self.camera_id = -1
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._grab_frame)

        # It's better to initialize the camera when explicitly told to,
        # or if a default camera_id >= 0 is provided.
        # For now, we'll let set_active_camera handle the initial setup if camera_id >=0.
        # if camera_id >= 0:
        #     self.set_active_camera(camera_id) # This would be called from MainWindow after instantiation

    def set_active_camera(self, camera_id: int):
        log.info(f"Attempting to set active camera to ID: {camera_id}")
        if self.timer.isActive():
            self.timer.stop()
        if self.cap:
            self.cap.release()
            self.cap = None
            log.info(f"Released previous camera (ID: {self.camera_id})")

        self.camera_id = camera_id
        if self.camera_id >= 0:
            try:
                self.cap = cv2.VideoCapture(self.camera_id, cv2.CAP_DSHOW)
                if not self.cap.isOpened():
                    self.cap = None # Ensure cap is None if not opened
                    error_msg = f"Cannot open camera ID: {self.camera_id}"
                    log.error(error_msg)
                    self.camera_error.emit(error_msg, -1) # -1 as a generic error code
                    self.label.setText(f"Error: Could not open Camera {self.camera_id}")
                    return False # Indicate failure

                log.info(f"Successfully opened camera ID: {self.camera_id}")
                # Optionally set default resolution or attempt to get actual resolution
                # For now, let's assume default or it will be set by set_active_resolution
                
                # --- Placeholder for resolution detection ---
                # This part is complex with OpenCV. For now, emit a placeholder or common list.
                # In a real scenario, you'd try to get valid resolutions here.
                # Example:
                # common_resolutions = ["640x480", "1280x720", "1920x1080"]
                # self.camera_resolutions_updated.emit(common_resolutions)
                # log.info(f"Emitted placeholder resolutions: {common_resolutions}")
                # A more robust way is needed if you need dynamic resolution lists.
                # For now, MainWindow's CameraControlPanel might have default values.

                self.timer.start(30)  # Start ~33 fps timer for frame grabbing
                return True # Indicate success

            except Exception as e:
                error_msg = f"Exception opening camera ID {self.camera_id}: {e}"
                log.error(error_msg, exc_info=True)
                self.camera_error.emit(error_msg, -2) # -2 for exception
                self.label.setText(f"Exception: Camera {self.camera_id}")
                if self.cap: # Ensure release if partially opened then failed
                    self.cap.release()
                    self.cap = None
                return False # Indicate failure
        else:
            self.label.setText("No camera selected or camera disabled.")
            self.camera_resolutions_updated.emit([]) # No camera, no resolutions
            return True # Considered successful in terms of "no camera is now active"

    def set_active_resolution(self, width: int, height: int):
        if self.cap and self.cap.isOpened():
            log.info(f"Attempting to set resolution to {width}x{height} for camera ID: {self.camera_id}")
            ret_w = self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            ret_h = self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            if ret_w and ret_h:
                # Verify if the resolution was actually set (some cameras ignore this)
                actual_w = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                actual_h = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                log.info(f"Set resolution for camera ID {self.camera_id}. Requested: {width}x{height}, Actual: {int(actual_w)}x{int(actual_h)}")
                # You might want to emit an error if actual doesn't match requested significantly
            else:
                log.warning(f"Failed to set resolution {width}x{height} for camera ID: {self.camera_id}. (ret_w: {ret_w}, ret_h: {ret_h})")
                # self.camera_error.emit(f"Failed to set resolution {width}x{height}", -3)
        else:
            log.warning("No active camera to set resolution for.")

    def _grab_frame(self):
        if self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if not ret:
                log.warning(f"Failed to grab frame from camera ID: {self.camera_id}")
                # self.camera_error.emit("Failed to grab frame", -4) # Be cautious with emitting errors in a loop
                return

            # Keep the raw BGR frame for recording if needed
            bgr_frame_for_recording = frame.copy() # Make a copy if you modify `frame` before emitting

            # Convert BGR (OpenCV default) to RGB for QImage
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_frame.shape
            bytes_per_line = ch * w
            qimg = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
            
            self.label.setPixmap(QPixmap.fromImage(qimg))
            self.frame_ready.emit(qimg.copy(), bgr_frame_for_recording) # Emit a copy of QImage if it's used elsewhere
        else:
            # If no camera, or not opened, ensure timer doesn't keep running uselessly or stop it
            # self.timer.stop() # Or ensure it's only started when cap is valid
            pass


    def get_current_resolution(self): # MainWindow tries to use this for TrialRecorder
        if self.cap and self.cap.isOpened():
            width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if width > 0 and height > 0:
                return QSize(width, height) # Return QSize as used in MainWindow
        return QSize() # Return an empty QSize if not available

    def closeEvent(self, event):
        log.info("QtCameraWidget closeEvent called.")
        self.timer.stop()
        if self.cap:
            self.cap.release()
            self.cap = None
            log.info(f"Released camera ID: {self.camera_id} during closeEvent")
        super().closeEvent(event)