# src/threads/qtcamera_widget.py
import cv2
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import QTimer, pyqtSignal, Qt, QSize
from PyQt5.QtGui import QImage, QPixmap
import logging
import json
import os

log = logging.getLogger(__name__)

# Define PROFILE_DIR relative to this file's location
# Assuming qtcamera_widget.py is in src/threads/ and profiles are in src/camera_profiles/
PROFILE_DIR = os.path.join(os.path.dirname(__file__), '..', 'camera_profiles')
if not os.path.isdir(PROFILE_DIR):
    log.warning(f"Camera profiles directory not found: {PROFILE_DIR}")
    # You might want to create it if it doesn't exist, or handle this more gracefully
    try:
        os.makedirs(PROFILE_DIR, exist_ok=True)
        log.info(f"Created camera profiles directory: {PROFILE_DIR}")
    except Exception as e:
        log.error(f"Could not create camera profiles directory {PROFILE_DIR}: {e}")


class QtCameraWidget(QWidget):
    frame_ready = pyqtSignal(QImage, object)
    camera_error = pyqtSignal(str, int)
    camera_resolutions_updated = pyqtSignal(list)
    camera_properties_updated = pyqtSignal(dict) # Emits dict of {prop_name: value, prop_name_range: (min,max), prop_name_default: val}

    def __init__(self, camera_id: int = -1, camera_description: str = "", parent=None):
        super().__init__(parent)
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setText("Camera feed will appear here.")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)

        self.cap = None
        self.camera_id = camera_id # Store initial camera_id
        self.camera_description = camera_description
        self.active_profile = None
        self.full_frame_width = 0 # To store actual full frame width from camera
        self.full_frame_height = 0# To store actual full frame height from camera

        # ROI attributes (for software ROI)
        self.roi_x, self.roi_y, self.roi_w, self.roi_h = 0, 0, 0, 0 # 0,0 for w,h means use full frame

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._grab_frame)
        
        self.load_camera_profile() # Load profile based on initial description

        # If a camera_id was provided at init, attempt to set it.
        # MainWindow will typically call set_active_camera explicitly after UI is up.
        # if self.camera_id >= 0:
        #     self.set_active_camera(self.camera_id, self.camera_description)


    def load_camera_profile(self):
        self.active_profile = None
        if not self.camera_description:
            log.debug("No camera description provided, cannot load specific profile.")
            return

        try:
            if not os.path.isdir(PROFILE_DIR):
                log.warning(f"Camera profiles directory does not exist: {PROFILE_DIR}")
                return

            for profile_file in os.listdir(PROFILE_DIR):
                if profile_file.endswith(".json"):
                    filepath = os.path.join(PROFILE_DIR, profile_file)
                    with open(filepath, 'r') as f:
                        profile_data = json.load(f)
                        for identifier in profile_data.get("model_identifiers", []):
                            if identifier.lower() in self.camera_description.lower():
                                self.active_profile = profile_data
                                log.info(f"Loaded camera profile: {profile_file} for {self.camera_description}")
                                return
            log.info(f"No specific profile found for: {self.camera_description}. Using generic settings.")
        except Exception as e:
            log.error(f"Error loading camera profiles from {PROFILE_DIR}: {e}", exc_info=True)

    def set_active_camera(self, camera_id: int, camera_description: str = ""):
        log.info(f"Attempting to set active camera to ID: {camera_id} ({camera_description})")
        if self.timer.isActive():
            self.timer.stop()
        if self.cap:
            self.cap.release()
            self.cap = None
            log.info(f"Released previous camera (ID: {self.camera_id})")

        self.camera_id = camera_id
        self.camera_description = camera_description
        self.load_camera_profile()

        if self.camera_id >= 0:
            try:
                self.cap = cv2.VideoCapture(self.camera_id, cv2.CAP_DSHOW)
                if not self.cap.isOpened():
                    self.cap = None
                    error_msg = f"Cannot open camera ID: {self.camera_id}"
                    log.error(error_msg)
                    self.camera_error.emit(error_msg, -1)
                    self.label.setText(f"Error: Could not open Camera {self.camera_id}")
                    return False

                log.info(f"Successfully opened camera ID: {self.camera_id}")

                # --- Resolution Handling ---
                target_w, target_h = 0, 0
                if self.active_profile:
                    default_res_label = self.active_profile.get("default_resolution_label")
                    for res_info in self.active_profile.get("resolutions", []):
                        if default_res_label and res_info["label"] == default_res_label:
                            target_w, target_h = res_info["width"], res_info["height"]
                            break
                    if target_w == 0 and self.active_profile.get("resolutions"): # Fallback to first in list
                         res_info = self.active_profile["resolutions"][0]
                         target_w, target_h = res_info["width"], res_info["height"]
                
                if target_w > 0 and target_h > 0:
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, target_w)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, target_h)
                else: # Generic fallback if no profile or no res in profile
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920) # A common high resolution
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

                self.full_frame_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                self.full_frame_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                log.info(f"Camera {self.camera_id} actual resolution: {self.full_frame_width}x{self.full_frame_height}")
                
                # Set initial ROI from profile or to full frame
                self.reset_roi_to_default()


                # Emit available resolutions (from profile or just the current one)
                if self.active_profile and "resolutions" in self.active_profile:
                    res_list_str = [r["label"] for r in self.active_profile["resolutions"]]
                    self.camera_resolutions_updated.emit(res_list_str)
                else:
                    self.camera_resolutions_updated.emit([f"{self.full_frame_width}x{self.full_frame_height}"])

                self.query_and_emit_camera_properties() # Query and send initial properties to UI
                self.timer.start(30)
                return True

            except Exception as e:
                error_msg = f"Exception opening camera ID {self.camera_id}: {e}"
                log.error(error_msg, exc_info=True)
                self.camera_error.emit(error_msg, -2)
                self.label.setText(f"Exception: Camera {self.camera_id}")
                if self.cap: self.cap.release(); self.cap = None
                return False
        else:
            self.label.setText("No camera selected or camera disabled.")
            self.camera_resolutions_updated.emit([])
            self.active_profile = None
            self.camera_properties_updated.emit({}) # Emit empty dict
            return True # Successfully set to "no camera"

    def set_active_resolution(self, width: int, height: int):
        if self.cap and self.cap.isOpened():
            log.info(f"Attempting to set resolution to {width}x{height} for camera ID: {self.camera_id}")
            was_timing = self.timer.isActive()
            if was_timing: self.timer.stop()

            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            
            self.full_frame_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.full_frame_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            log.info(f"Resolution for camera ID {self.camera_id}. Requested: {width}x{height}, Actual: {self.full_frame_width}x{self.full_frame_height}")

            self.reset_roi_to_default() # Reset ROI when resolution changes
            self.query_and_emit_camera_properties() # Re-query props, some might change with resolution

            if was_timing: self.timer.start(30)
        else:
            log.warning("No active camera to set resolution for.")

    def reset_roi_to_default(self):
        """Sets ROI to default from profile or full frame."""
        if self.active_profile and "roi" in self.active_profile:
            roi_profile = self.active_profile["roi"]
            self.roi_x = roi_profile.get("default_x", 0)
            self.roi_y = roi_profile.get("default_y", 0)
            # Use factors if present, otherwise assume w,h are absolute or 0 for full
            w_factor = roi_profile.get("default_w_factor", 0)
            h_factor = roi_profile.get("default_h_factor", 0)
            if w_factor > 0 and self.full_frame_width > 0:
                self.roi_w = int(self.full_frame_width * w_factor)
            else:
                self.roi_w = roi_profile.get("default_w", 0) # if 0, means full width

            if h_factor > 0 and self.full_frame_height > 0:
                self.roi_h = int(self.full_frame_height * h_factor)
            else:
                self.roi_h = roi_profile.get("default_h", 0) # if 0, means full height
        else: # No profile, default to full frame
            self.roi_x, self.roi_y, self.roi_w, self.roi_h = 0, 0, 0, 0
        log.info(f"ROI reset to: x:{self.roi_x} y:{self.roi_y} w:{self.roi_w} h:{self.roi_h}")


    def set_software_roi(self, x, y, w, h):
        # Basic validation, more robust checks might be needed based on full_frame_width/height
        if self.full_frame_width > 0 and self.full_frame_height > 0:
             self.roi_x = max(0, min(x, self.full_frame_width -1))
             self.roi_y = max(0, min(y, self.full_frame_height -1))
             self.roi_w = max(0, min(w, self.full_frame_width - self.roi_x))
             self.roi_h = max(0, min(h, self.full_frame_height - self.roi_y))
        else: # Can't validate if we don't know full frame size
             self.roi_x, self.roi_y, self.roi_w, self.roi_h = x,y,w,h

        log.info(f"Software ROI set to x:{self.roi_x}, y:{self.roi_y}, w:{self.roi_w}, h:{self.roi_h}")


    def _grab_frame(self):
        if self.cap and self.cap.isOpened():
            ret, full_frame = self.cap.read()
            if not ret:
                log.warning(f"Failed to grab frame from camera ID: {self.camera_id}")
                return

            frame_to_process = full_frame
            if self.roi_w > 0 and self.roi_h > 0: # If ROI width and height are set
                # Ensure ROI is within current full_frame dimensions after potential clamping in set_software_roi
                clamped_y2 = min(self.roi_y + self.roi_h, self.full_frame_height)
                clamped_x2 = min(self.roi_x + self.roi_w, self.full_frame_width)
                clamped_y1 = min(self.roi_y, clamped_y2) # ensure y1 <= y2
                clamped_x1 = min(self.roi_x, clamped_x2) # ensure x1 <= x2

                if clamped_y2 > clamped_y1 and clamped_x2 > clamped_x1:
                    frame_to_process = full_frame[clamped_y1:clamped_y2, clamped_x1:clamped_x2]
                else:
                    log.debug("ROI resulted in zero size, using full frame.") # Use debug to avoid spamming logs
                    frame_to_process = full_frame # Fallback if ROI is bad
            
            bgr_frame_for_recording = frame_to_process.copy()
            rgb_frame = cv2.cvtColor(frame_to_process, cv2.COLOR_BGR2RGB)
            
            h, w, ch = rgb_frame.shape
            if h == 0 or w == 0: # Crop might result in empty frame if ROI is bad
                log.warning("Frame to display has zero height or width after ROI. Skipping display.")
                return

            bytes_per_line = ch * w
            qimg = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
            self.label.setPixmap(QPixmap.fromImage(qimg))
            self.frame_ready.emit(qimg.copy(), bgr_frame_for_recording)
        else:
            pass

    def get_current_resolution(self):
        # This should now return the full frame resolution, not potentially cropped.
        if self.cap and self.cap.isOpened():
            # Return the stored full frame dimensions
            if self.full_frame_width > 0 and self.full_frame_height > 0:
                 return QSize(self.full_frame_width, self.full_frame_height)
            else: # Fallback if not stored yet
                 width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                 height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                 if width > 0 and height > 0: return QSize(width, height)
        return QSize()

    def _get_cv2_prop_from_profile(self, control_key: str, prop_name_in_config: str = "prop"):
        """Gets the OpenCV property ID string (e.g., 'CAP_PROP_BRIGHTNESS') from the active profile."""
        if self.active_profile and "controls" in self.active_profile:
            control_config = self.active_profile["controls"].get(control_key)
            if control_config and prop_name_in_config in control_config:
                return control_config[prop_name_in_config]
        return None # Return None if not found in profile

    def _set_camera_property(self, control_key: str, value: float, prop_name_in_config: str = "prop"):
        if not (self.cap and self.cap.isOpened()):
            log.warning(f"Cannot set {control_key}: Camera not open.")
            return False

        prop_str = self._get_cv2_prop_from_profile(control_key, prop_name_in_config)
        
        # Generic fallback if not in profile (less ideal, but provides some functionality)
        if not prop_str:
            generic_map = {
                "brightness": "CAP_PROP_BRIGHTNESS", "gain": "CAP_PROP_GAIN",
                "exposure": "CAP_PROP_EXPOSURE", # For direct exposure value
                "auto_exposure": "CAP_PROP_AUTO_EXPOSURE" # For auto exposure mode
            }
            prop_str = generic_map.get(control_key)

        if prop_str and hasattr(cv2, prop_str):
            prop_id = getattr(cv2, prop_str)
            ret = self.cap.set(prop_id, float(value))
            actual_value = self.cap.get(prop_id)
            log.info(f"Set {control_key} ({prop_str}) to {value}, success: {ret}. Actual: {actual_value}")
            if not ret: log.warning(f"Failed to set {control_key} to {value}")
            return ret
        else:
            log.warning(f"Property for '{control_key}' ('{prop_name_in_config}':'{prop_str}') not found in cv2 or profile.")
            return False

    def set_brightness(self, value: int):
        if self._set_camera_property("brightness", float(value)):
            self.query_and_emit_camera_properties()

    def set_gain(self, value: int):
        if self._set_camera_property("gain", float(value)):
            self.query_and_emit_camera_properties()

    def set_exposure(self, value: int): # This 'value' is what the slider provides
        # Auto exposure might need to be off. Profile can guide this.
        if self.active_profile and "controls" in self.active_profile and "exposure" in self.active_profile["controls"]:
            exp_config = self.active_profile["controls"]["exposure"]
            auto_prop_str = exp_config.get("auto_prop")
            auto_off_val = exp_config.get("auto_off_value")

            if auto_prop_str and auto_off_val is not None:
                 current_auto_exposure = self.cap.get(getattr(cv2, auto_prop_str))
                 # Check if auto exposure is on (value might not be exactly auto_on_value, but not auto_off_value)
                 if abs(current_auto_exposure - auto_off_val) > 1e-3 : # If not in manual mode
                      log.warning("Manual exposure set attempt, but auto-exposure seems to be ON. "
                                  "Set auto-exposure to manual first for predictable results.")
        
        if self._set_camera_property("exposure", float(value), prop_name_in_config="value_prop"):
            self.query_and_emit_camera_properties()

    def set_auto_exposure(self, enable_auto: bool): # True to enable auto, False for manual
        target_mode_value = None
        if self.active_profile and "controls" in self.active_profile and "exposure" in self.active_profile["controls"]:
            exp_config = self.active_profile["controls"]["exposure"]
            if enable_auto:
                target_mode_value = exp_config.get("auto_on_value")
            else:
                target_mode_value = exp_config.get("auto_off_value")
        else: # Generic fallback if no profile
            target_mode_value = 0.75 if enable_auto else 0.25 # Common UVC values

        if target_mode_value is not None:
            if self._set_camera_property("exposure", target_mode_value, prop_name_in_config="auto_prop"):
                 self.query_and_emit_camera_properties()
        else:
            log.warning("Auto exposure on/off values not defined in profile for 'exposure' control.")


    def query_and_emit_camera_properties(self):
        if not (self.cap and self.cap.isOpened()):
            self.camera_properties_updated.emit({}) # Emit empty if no camera
            return

        properties_payload = {"controls": {}, "roi": {
            "x": self.roi_x, "y": self.roi_y, "w": self.roi_w, "h": self.roi_h,
            "max_w": self.full_frame_width, "max_h": self.full_frame_height
        }}
        
        # Default generic properties to try if no profile
        controls_to_query_config = {
            "brightness": {"prop": "CAP_PROP_BRIGHTNESS"},
            "gain": {"prop": "CAP_PROP_GAIN"},
            "exposure": {"prop": "CAP_PROP_EXPOSURE", "value_prop": "CAP_PROP_EXPOSURE", "auto_prop": "CAP_PROP_AUTO_EXPOSURE"}
            # Add more generic ones if needed
        }

        if self.active_profile and "controls" in self.active_profile:
            controls_to_query_config = self.active_profile["controls"] # Use profile if available
        
        for control_name, config in controls_to_query_config.items():
            prop_data = {}
            # Get main value
            val_prop_str = config.get("value_prop", config.get("prop")) # "value_prop" for exposure, "prop" for others
            if val_prop_str and hasattr(cv2, val_prop_str):
                prop_data["value"] = self.cap.get(getattr(cv2, val_prop_str))
            
            # Get auto mode if specified for this control (e.g., exposure)
            auto_prop_str = config.get("auto_prop")
            if auto_prop_str and hasattr(cv2, auto_prop_str):
                prop_data["auto_mode"] = self.cap.get(getattr(cv2, auto_prop_str))
                # Determine if it's "on" based on profile values
                if "auto_on_value" in config and "auto_off_value" in config:
                    # Compare float values carefully
                    if abs(prop_data["auto_mode"] - config["auto_on_value"]) < 1e-3:
                         prop_data["is_auto_on"] = True
                    elif abs(prop_data["auto_mode"] - config["auto_off_value"]) < 1e-3:
                         prop_data["is_auto_on"] = False
                    # else, it's an indeterminate state or not matching profile values

            # Add range and default from profile for UI to use
            if "min" in config: prop_data["min"] = config["min"]
            if "max" in config: prop_data["max"] = config["max"]
            if "default" in config: prop_data["default"] = config["default"]
            if "enabled" in config: prop_data["enabled"] = config["enabled"]
            if "label" in config: prop_data["label"] = config.get("label", control_name)

            if prop_data: # If we got any data for this control
                properties_payload["controls"][control_name] = prop_data
        
        log.debug(f"Queried camera properties payload: {properties_payload}")
        self.camera_properties_updated.emit(properties_payload)

    def closeEvent(self, event):
        log.info("QtCameraWidget closeEvent called.")
        self.timer.stop()
        if self.cap:
            self.cap.release()
            self.cap = None
            log.info(f"Released camera ID: {self.camera_id} during closeEvent")
        super().closeEvent(event)