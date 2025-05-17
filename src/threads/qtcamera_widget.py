import cv2
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy
from PyQt5.QtCore import pyqtSignal, Qt, QSize
from PyQt5.QtGui import QImage, QPixmap, QFont
import logging
import json
import os

from threads.camera_thread import CameraThread

log = logging.getLogger(__name__)

PROFILE_DIR = os.path.join(os.path.dirname(__file__), "..", "camera_profiles")
if not os.path.isdir(PROFILE_DIR):
    log.warning(f"Camera profiles directory not found: {PROFILE_DIR}")
    try:
        os.makedirs(PROFILE_DIR, exist_ok=True)
        log.info(f"Created camera profiles directory: {PROFILE_DIR}")
    except Exception as e:
        log.error(f"Could not create camera profiles directory {PROFILE_DIR}: {e}")


class QtCameraWidget(QWidget):
    frame_ready = pyqtSignal(QImage, object)
    camera_error = pyqtSignal(str, int)
    camera_resolutions_updated = pyqtSignal(list)
    camera_properties_updated = pyqtSignal(dict)

    def __init__(self, camera_id: int = -1, camera_description: str = "", parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumSize(1080, 1080)
        self._aspect_ratio = 1 / 1
        # QSS Suggestion: QtCameraWidget { background-color: #yourCameraBg; border: 1px solid #yourBorderColor; }

        self.viewfinder_label = QLabel(self)
        self.viewfinder_label.setAlignment(Qt.AlignCenter)
        # QSS Suggestion: QtCameraWidget > QLabel { color: #placeholderTextColor; }
        font = QFont()
        font.setPointSize(12)  # Larger font for placeholder
        self.viewfinder_label.setFont(font)
        self.viewfinder_label.setScaledContents(
            False
        )  # Important for quality when scaling pixmap
        self.viewfinder_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self._camera_thread = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.viewfinder_label)

        self.cap = None
        self.camera_id = camera_id
        self.camera_description = camera_description
        self.active_profile = None
        self.full_frame_width = 0
        self.full_frame_height = 0
        self.roi_x, self.roi_y, self.roi_w, self.roi_h = 0, 0, 0, 0
        self._last_pixmap_displayed = None


        self.load_camera_profile()  # Load based on initial description if provided
        self._update_placeholder_text()  # Initial placeholder

    def _update_placeholder_text(self, message=None):
        if self.cap and self.cap.isOpened():
            # If camera is active, placeholder shouldn't be visible,
            # but could be called if stopping camera.
            self.viewfinder_label.setText("")  # Clear text if showing frames
        elif message:
            self.viewfinder_label.setText(message)
        elif self.camera_id == -1:
            self.viewfinder_label.setText(
                "No Camera Selected\n\nSelect a camera device from the controls."
            )
        else:
            self.viewfinder_label.setText(
                f"Camera {self.camera_id} ({self.camera_description})\nNot Active or Error."
            )
        # Ensure any old pixmap is cleared if showing text placeholder
        if not (self.cap and self.cap.isOpened()):
            self.viewfinder_label.setPixmap(QPixmap())  # Clear existing pixmap
            self._last_pixmap_displayed = None

    def load_camera_profile(self):
        # ... (no changes needed in this method from previous version, ensure it works)
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
                    with open(filepath, "r") as f:
                        profile_data = json.load(f)
                        for identifier in profile_data.get("model_identifiers", []):
                            if identifier.lower() in self.camera_description.lower():
                                self.active_profile = profile_data
                                log.info(
                                    f"Loaded camera profile: {profile_file} for {self.camera_description}"
                                )
                                return
            log.info(
                f"No specific profile found for: {self.camera_description}. Using generic settings."
            )
        except Exception as e:
            log.error(
                f"Error loading camera profiles from {PROFILE_DIR}: {e}", exc_info=True
            )

    def set_active_camera(self, camera_id: int, camera_description: str = ""):
        log.info(
            f"Attempting to set active camera to ID: {camera_id} ('{camera_description}')"
        )
        
        if self.cap:
            self.cap.release()
            self.cap = None
            log.info(f"Released previous camera (ID: {self.camera_id})")

        self.camera_id = camera_id
        self.camera_description = camera_description
        self.load_camera_profile()  # Reload profile for the new camera

        if self.camera_id >= 0:  # Valid camera ID
            try:
                # Preferred API: cv2.CAP_DSHOW for Windows, can try others if needed
                self.cap = cv2.VideoCapture(self.camera_id, cv2.CAP_DSHOW)
                if not self.cap.isOpened():
                    # Try default API if DSHOW failed
                    log.warning(
                        f"Failed to open camera ID {self.camera_id} with CAP_DSHOW, trying default API."
                    )
                    self.cap = cv2.VideoCapture(self.camera_id)
                    if not self.cap.isOpened():
                        self.cap = None  # Ensure it's None
                        error_msg = (
                            f"Cannot open camera ID: {self.camera_id} with any backend."
                        )
                        log.error(error_msg)
                        self.camera_error.emit(error_msg, -1)
                        self._update_placeholder_text(
                            f"Error: Could not open Camera {self.camera_id}.\nCheck connections or drivers."
                        )
                        self.camera_resolutions_updated.emit([])
                        self.camera_properties_updated.emit({})  # Clear properties
                        return False

                log.info(
                    f"Successfully opened camera ID: {self.camera_id} ('{self.camera_description}')"
                )
                self._update_placeholder_text("")  # Clear placeholder

                target_w, target_h = 0, 0
                if self.active_profile:
                    default_res_label = self.active_profile.get(
                        "default_resolution_label"
                    )  # e.g., "1920x1080 @ 30fps"
                    res_options = self.active_profile.get("resolutions", [])

                    found_default = False
                    if default_res_label:
                        for res_info in res_options:  # res_info is a dict
                            if res_info.get("label") == default_res_label:
                                target_w, target_h = (
                                    res_info["width"],
                                    res_info["height"],
                                )
                                found_default = True
                                break
                    if (
                        not found_default and res_options
                    ):  # Fallback to first in profile list
                        res_info = res_options[0]
                        target_w, target_h = res_info["width"], res_info["height"]

                if target_w > 0 and target_h > 0:
                    log.info(
                        f"Setting camera {self.camera_id} resolution from profile to {target_w}x{target_h}"
                    )
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(target_w))
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(target_h))
                else:  # Generic fallback if no profile or no res in profile
                    log.info(
                        f"No profile resolution for {self.camera_id}, trying generic 1920x1080."
                    )
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920.0)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080.0)
                    # If that fails, try a very common one
                    if int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)) == 0:
                        log.warning("Failed to set 1920x1080, trying 640x480.")
                        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640.0)
                        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480.0)

                self.full_frame_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                self.full_frame_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

                if self.full_frame_width == 0 or self.full_frame_height == 0:
                    log.error(
                        f"Camera {self.camera_id} reported 0x0 resolution after attempting to set. Cannot proceed."
                    )
                    self.cap.release()
                    self.cap = None
                    self.camera_error.emit(
                        f"Camera {self.camera_id} reported invalid resolution (0x0).",
                        -1,
                    )
                    self._update_placeholder_text(
                        f"Error: Camera {self.camera_id}\nreported invalid resolution."
                    )
                    self.camera_resolutions_updated.emit([])
                    self.camera_properties_updated.emit({})
                    return False

                log.info(
                    f"Camera {self.camera_id} actual resolution: {self.full_frame_width}x{self.full_frame_height}"
                )

                self.reset_roi_to_default()  # Sets ROI based on (new) full_frame_width/height

                # Emit available resolutions
                res_list_for_ui = []
                if self.active_profile and "resolutions" in self.active_profile:
                    # Profile might have labels like "1920x1080 @ 30fps", UI needs "WIDTHxHEIGHT"
                    for r_info in self.active_profile["resolutions"]:
                        res_list_for_ui.append(f"{r_info['width']}x{r_info['height']}")
                    self.camera_resolutions_updated.emit(
                        list(set(res_list_for_ui))
                    )  # Unique resolutions
                else:  # No profile, just emit current actual resolution
                    self.camera_resolutions_updated.emit(
                        [f"{self.full_frame_width}x{self.full_frame_height}"]
                    )


                self.query_and_emit_camera_properties()

                # ── Stop old thread if any ─────────────────────────────────────
                if self._camera_thread:
                    self._camera_thread.stop()

                # ── Launch new capture thread ───────────────────────────────────
                w, h = self.full_frame_width, self.full_frame_height
                raw_fps = (
                   self.active_profile.get("default_fps", 30)
                   if self.active_profile
                   else 30
                )
                display_fps = min(raw_fps, 15)
                # ── Use a small display size for smooth preview ───────────────────────────
                disp_w, disp_h = 640, 480

                self._camera_thread = CameraThread(
                    device_index=self.camera_id,
                    display_width   = disp_w,
                    display_height  = disp_h,
                    fps             = display_fps,
                    parent=self,
                )

                self._camera_thread.frameReady.connect(self._on_thread_frame)
                self._camera_thread.start()

                return True

            except Exception as e:
                error_msg = (
                    f"Exception opening/configuring camera ID {self.camera_id}: {e}"
                )
                log.error(error_msg, exc_info=True)
                self.camera_error.emit(error_msg, -2)  # -2 for exception
                self._update_placeholder_text(
                    f"Exception with Camera {self.camera_id}.\nSee logs for details."
                )
                if self.cap:
                    self.cap.release()
                    self.cap = None
                self.camera_resolutions_updated.emit([])
                self.camera_properties_updated.emit({})
                return False
        else:  # camera_id < 0 (no camera selected / disabled)
            self._update_placeholder_text()  # Show "No Camera Selected"
            self.camera_resolutions_updated.emit([])
            self.active_profile = None  # Clear profile
            self.camera_properties_updated.emit(
                {}
            )  # Emit empty dict to disable controls
            return True  # Successfully set to "no camera" state

    def set_active_resolution(self, width: int, height: int):
        # ... (no significant changes needed here, but ensure logging is good)
        if self.cap and self.cap.isOpened():
            log.info(
                f"Attempting to set resolution to {width}x{height} for camera ID: {self.camera_id}"
            )

            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))

            actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            if actual_w == 0 or actual_h == 0:  # Check if resolution set failed badly
                log.warning(
                    f"Failed to set {width}x{height}. Camera reported {actual_w}x{actual_h}. Reverting or erroring."
                )
                # Optionally, try to revert to previous self.full_frame_width/height or emit error
                # For now, just log and proceed, UI might show 0x0 if it happens
                self.camera_error.emit(
                    f"Failed to set resolution {width}x{height}. Camera reported {actual_w}x{actual_h}.",
                    -1,
                )

            self.full_frame_width = actual_w
            self.full_frame_height = actual_h
            log.info(
                f"Resolution for camera ID {self.camera_id}. Requested: {width}x{height}, Actual: {self.full_frame_width}x{self.full_frame_height}"
            )

            self.reset_roi_to_default()
            self.query_and_emit_camera_properties()

        else:
            log.warning("No active camera to set resolution for.")

    def reset_roi_to_default(self):
        # ... (logic seems okay, ensure logging)
        if (
            self.active_profile
            and "roi" in self.active_profile
            and isinstance(self.active_profile["roi"], dict)
        ):
            roi_profile = self.active_profile["roi"]
            # Check if full_frame_width/height are valid before calculating factors
            if self.full_frame_width <= 0 or self.full_frame_height <= 0:
                log.warning(
                    "Cannot calculate ROI from factors: full frame dimensions are invalid."
                )
                self.roi_x, self.roi_y, self.roi_w, self.roi_h = (
                    0,
                    0,
                    0,
                    0,
                )  # Fallback to full frame (software interpretation)
            else:
                self.roi_x = roi_profile.get("default_x", 0)
                self.roi_y = roi_profile.get("default_y", 0)

                w_factor = roi_profile.get(
                    "default_w_factor"
                )  # No default for factor itself
                h_factor = roi_profile.get("default_h_factor")

                if w_factor is not None and w_factor > 0:  # Factor explicitly provided
                    self.roi_w = int(self.full_frame_width * w_factor)
                else:  # No factor, use absolute default_w or 0 for full
                    self.roi_w = roi_profile.get("default_w", 0)

                if h_factor is not None and h_factor > 0:
                    self.roi_h = int(self.full_frame_height * h_factor)
                else:
                    self.roi_h = roi_profile.get("default_h", 0)
        else:
            self.roi_x, self.roi_y, self.roi_w, self.roi_h = 0, 0, 0, 0
        log.info(
            f"Software ROI reset to: x:{self.roi_x} y:{self.roi_y} w:{self.roi_w} h:{self.roi_h} (relative to {self.full_frame_width}x{self.full_frame_height})"
        )
        # After resetting, emit updated properties so UI reflects this ROI
        self.query_and_emit_camera_properties()

    def set_software_roi(self, x, y, w, h):
        # ... (logic seems okay, ensure logging and validation against current full_frame_width/height)
        if self.full_frame_width > 0 and self.full_frame_height > 0:
            self.roi_x = max(0, min(x, self.full_frame_width - 1))
            self.roi_y = max(0, min(y, self.full_frame_height - 1))
            # Ensure w and h are at least 0. If 0, it means full dimension from x/y.
            self.roi_w = max(
                0,
                min(
                    w,
                    (
                        self.full_frame_width - self.roi_x
                        if w > 0
                        else self.full_frame_width - self.roi_x
                    ),
                ),
            )
            self.roi_h = max(
                0,
                min(
                    h,
                    (
                        self.full_frame_height - self.roi_y
                        if h > 0
                        else self.full_frame_height - self.roi_y
                    ),
                ),
            )
        else:
            self.roi_x, self.roi_y, self.roi_w, self.roi_h = x, y, w, h
        log.info(
            f"Software ROI set to x:{self.roi_x}, y:{self.roi_y}, w:{self.roi_w}, h:{self.roi_h}"
        )
        # After setting, emit updated properties
        self.query_and_emit_camera_properties()

    def _grab_frame(self):
        if not (self.cap and self.cap.isOpened()):
            # This case should ideally be prevented by timer not running or set_active_camera failing.
            # If it happens, ensure placeholder is shown.
            self._update_placeholder_text(f"Camera {self.camera_id} not available.")
            return

        ret, full_frame = self.cap.read()
        if not ret or full_frame is None:
            log.warning(
                f"Failed to grab frame from camera ID: {self.camera_id}. Ret: {ret}"
            )
            # Consider emitting a camera_error or attempting to re-initialize if this persists.
            # For now, just skip this frame. If it happens many times, the feed will appear frozen.
            return

        frame_to_process = full_frame
        # Apply software ROI if w and h are specified (greater than 0)
        # If roi_w or roi_h is 0, it implies "full width/height from this point"
        use_roi_w = self.roi_w if self.roi_w > 0 else self.full_frame_width - self.roi_x
        use_roi_h = (
            self.roi_h if self.roi_h > 0 else self.full_frame_height - self.roi_y
        )

        if (
            use_roi_w > 0
            and use_roi_h > 0
            and (self.roi_x > 0 or self.roi_y > 0 or self.roi_w > 0 or self.roi_h > 0)
        ):  # Check if ROI is actually different from full frame

            # Ensure ROI coordinates are valid for the current full_frame dimensions
            y1 = max(0, self.roi_y)
            y2 = min(self.roi_y + use_roi_h, self.full_frame_height)
            x1 = max(0, self.roi_x)
            x2 = min(self.roi_x + use_roi_w, self.full_frame_width)

            if y2 > y1 and x2 > x1:  # Valid ROI dimensions
                frame_to_process = full_frame[y1:y2, x1:x2]
            else:
                log.debug("ROI resulted in zero or negative size, using full frame.")
                frame_to_process = full_frame

        if (
            frame_to_process is None
            or frame_to_process.shape[0] == 0
            or frame_to_process.shape[1] == 0
        ):
            log.warning(
                "Frame to display has zero height or width after ROI. Skipping display."
            )
            return

        bgr_frame_for_recording = frame_to_process.copy()  # For data emitting

        try:
            rgb_frame = cv2.cvtColor(frame_to_process, cv2.COLOR_BGR2RGB)
        except cv2.error as e:
            log.error(
                f"OpenCV error during BGR2RGB conversion: {e}. Frame shape: {frame_to_process.shape}"
            )
            return  # Skip frame

        h, w, ch = rgb_frame.shape
        bytes_per_line = ch * w
        qimg = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format_RGB888)

        # Scale pixmap smoothly, preserving aspect ratio, to fit the label
        # self.viewfinder_label.setPixmap(pix.scaled(self.viewfinder_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        # Store this qimg as the "last good one" for resizing events
        # self._last_qimage_displayed = qimg.copy() # Keep a copy for resize events

        # Optimized display: create pixmap only once, scale on demand in resizeEvent or if label size changes
        self._last_pixmap_displayed = QPixmap.fromImage(
            qimg
        )  # Store the full-res pixmap
        self._update_displayed_pixmap()  # Scale and set it

        self.frame_ready.emit(
            qimg.copy(), bgr_frame_for_recording
        )  # Emit copies for safety

    def _update_displayed_pixmap(self):
        if self._last_pixmap_displayed and not self._last_pixmap_displayed.isNull():
            self.viewfinder_label.setPixmap(
                self._last_pixmap_displayed.scaled(
                    self.viewfinder_label.size(),  # Target size is the label's current size
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
        else:  # No valid pixmap, ensure placeholder or clear
            if not (self.cap and self.cap.isOpened()):  # If camera is not running
                self._update_placeholder_text()  # Refresh placeholder if needed
            else:  # Camera is running but no pixmap (shouldn't happen often)
                self.viewfinder_label.clear()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # When widget is resized, re-scale the last captured pixmap to fit the new label size
        self._update_displayed_pixmap()

    def get_current_resolution(self):
        if self.cap and self.cap.isOpened():
            if self.full_frame_width > 0 and self.full_frame_height > 0:
                return QSize(self.full_frame_width, self.full_frame_height)
            else:  # Fallback if not stored (should be rare after set_active_camera)
                width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                if width > 0 and height > 0:
                    return QSize(width, height)
        return QSize()  # Return empty QSize if no camera or zero dimensions

    # Methods for setting properties (_get_cv2_prop_from_profile, _set_camera_property, etc.)
    # and query_and_emit_camera_properties remain largely the same.
    # Ensure they handle cases where self.cap might be None or not opened gracefully.
    # ... (previous implementation of these methods is generally okay, ensure robustness) ...
    def _get_cv2_prop_from_profile(
        self, control_key: str, prop_name_in_config: str = "prop"
    ):
        if self.active_profile and "controls" in self.active_profile:
            control_config = self.active_profile["controls"].get(control_key)
            if control_config and prop_name_in_config in control_config:
                return control_config[prop_name_in_config]
        return None

    def _set_camera_property(
        self, control_key: str, value: float, prop_name_in_config: str = "prop"
    ):
        if not (self.cap and self.cap.isOpened()):
            log.warning(f"Cannot set {control_key}: Camera not open or not available.")
            return False

        prop_str = self._get_cv2_prop_from_profile(control_key, prop_name_in_config)

        if not prop_str:  # Generic fallback if not in profile
            generic_map = {
                "brightness": "CAP_PROP_BRIGHTNESS",
                "gain": "CAP_PROP_GAIN",
                "exposure": "CAP_PROP_EXPOSURE",
                "auto_exposure_mode": "CAP_PROP_AUTO_EXPOSURE",  # If 'exposure' key is used for mode
            }
            # If control_key is like "exposure" and prop_name_in_config is "auto_prop" in profile,
            # this generic map needs to be smarter or profile needs to be complete.
            # For now, assume prop_name_in_config helps differentiate.
            if prop_name_in_config == "prop":  # Main value property
                prop_str = generic_map.get(control_key)
            elif (
                prop_name_in_config == "auto_prop" and control_key == "exposure"
            ):  # Specific for auto exposure mode
                prop_str = generic_map.get("auto_exposure_mode")

        if prop_str and hasattr(cv2, prop_str):
            prop_id = getattr(cv2, prop_str)
            try:
                ret = self.cap.set(prop_id, float(value))
                actual_value = self.cap.get(prop_id)  # Get actual value after setting
                log.info(
                    f"Set CamProp '{control_key}' (OpenCV {prop_str}={prop_id}) to {value}, success: {ret}. Actual val: {actual_value:.2f}"
                )
                if not ret:
                    log.warning(
                        f"Failed to set {control_key} ({prop_str}) to {value} (cap.set returned False)."
                    )
                return ret
            except Exception as e_set_prop:
                log.error(
                    f"Exception setting CamProp '{control_key}' ({prop_str}) to {value}: {e_set_prop}"
                )
                return False
        else:
            log.warning(
                f"Property for '{control_key}' (config key:'{prop_name_in_config}', resolved OpenCV prop:'{prop_str}') not found in cv2 or profile."
            )
            return False

    def set_brightness(self, value: int):  # value from UI slider
        if self._set_camera_property("brightness", float(value)):
            self.query_and_emit_camera_properties()  # Refresh UI with actual value

    def set_gain(self, value: int):
        if self._set_camera_property("gain", float(value)):
            self.query_and_emit_camera_properties()

    def set_exposure(self, value: int):  # value from UI slider (manual exposure time)
        # Profile should guide if auto-exposure needs to be turned off first.
        # Some cameras manage this automatically, others require explicit mode switch.
        # For now, assume setting CAP_PROP_EXPOSURE implies manual if camera supports it.

        # Attempt to turn off auto-exposure if profile suggests it and it's on
        if (
            self.active_profile
            and "controls" in self.active_profile
            and "exposure" in self.active_profile["controls"]
        ):
            exp_config = self.active_profile["controls"]["exposure"]
            auto_prop_str = exp_config.get("auto_prop")  # e.g. CAP_PROP_AUTO_EXPOSURE
            auto_off_val = exp_config.get(
                "auto_off_value"
            )  # e.g. 0.0 or specific UVC value

            if (
                auto_prop_str
                and auto_off_val is not None
                and hasattr(cv2, auto_prop_str)
            ):
                current_auto_mode = self.cap.get(getattr(cv2, auto_prop_str))
                # Check if auto exposure is currently on (value might not be exactly auto_on_value,
                # but critically, if it's NOT the auto_off_value).
                # This logic can be tricky due to camera-specific values for auto modes.
                # A common UVC pattern is 0.25 for manual, 0.75 for auto.
                # If profile defines auto_off_value, check if current mode is NOT that.
                if (
                    abs(current_auto_mode - auto_off_val) > 1e-3
                ):  # If not in manual mode
                    log.info(
                        f"Exposure control: Auto-exposure seems ON (current mode {current_auto_mode}, profile manual_mode_val {auto_off_val}). Attempting to set manual mode first."
                    )
                    # self._set_camera_property("exposure", auto_off_val, prop_name_in_config="auto_prop") # Disable auto
                    # The set_auto_exposure method should handle this. Here we just log.
                    # The UI should ideally manage enabling/disabling the manual slider based on auto_exposure_cb.

        # Profile's "exposure" control should have "value_prop" for the actual exposure time setting
        # (e.g., CAP_PROP_EXPOSURE itself if not using a different prop for value when auto is off)
        value_prop_config_key = (
            "value_prop"
            if self.active_profile
            and "value_prop"
            in self.active_profile.get("controls", {}).get("exposure", {})
            else "prop"
        )

        if self._set_camera_property(
            "exposure", float(value), prop_name_in_config=value_prop_config_key
        ):
            self.query_and_emit_camera_properties()

    def set_auto_exposure(
        self, enable_auto: bool
    ):  # True to enable auto, False for manual
        target_mode_value = None
        # Profile's "exposure" control should define "auto_prop", "auto_on_value", "auto_off_value"
        if (
            self.active_profile
            and "controls" in self.active_profile
            and "exposure" in self.active_profile["controls"]
        ):
            exp_config = self.active_profile["controls"]["exposure"]
            if enable_auto:
                target_mode_value = exp_config.get("auto_on_value")
            else:  # Disable auto, enable manual
                target_mode_value = exp_config.get("auto_off_value")
        else:  # Generic fallback if no profile (common UVC values for CAP_PROP_AUTO_EXPOSURE)
            target_mode_value = 0.75 if enable_auto else 0.25

        if target_mode_value is not None:
            # Use "auto_prop" from profile for setting the mode
            if self._set_camera_property(
                "exposure", target_mode_value, prop_name_in_config="auto_prop"
            ):
                self.query_and_emit_camera_properties()  # Refresh UI
        else:
            log.warning(
                "Auto exposure on/off values not defined in profile for 'exposure' control's 'auto_prop'."
            )

    def query_and_emit_camera_properties(self):
        if not (self.cap and self.cap.isOpened()):
            self.camera_properties_updated.emit({})  # Emit empty to disable UI controls
            return

        properties_payload = {
            "controls": {},
            "roi": {  # Always include ROI info if camera is active
                "x": self.roi_x,
                "y": self.roi_y,
                "w": self.roi_w,
                "h": self.roi_h,
                "max_w": self.full_frame_width,
                "max_h": self.full_frame_height,
            },
        }

        # Define which controls to query based on profile or a generic set
        controls_to_query_from_profile = {}
        if self.active_profile and "controls" in self.active_profile:
            controls_to_query_from_profile = self.active_profile["controls"]
        else:  # Generic fallback (ensure these OpenCV Cap props exist)
            controls_to_query_from_profile = {
                "brightness": {
                    "prop": "CAP_PROP_BRIGHTNESS",
                    "min": 0,
                    "max": 255,
                    "enabled": hasattr(cv2, "CAP_PROP_BRIGHTNESS"),
                },
                "gain": {
                    "prop": "CAP_PROP_GAIN",
                    "min": 0,
                    "max": 100,
                    "enabled": hasattr(cv2, "CAP_PROP_GAIN"),
                },  # Max is arbitrary here
                "exposure": {  # For exposure, "prop" is usually the value, "auto_prop" is the mode
                    "prop": "CAP_PROP_EXPOSURE",
                    "min": -13,
                    "max": 0,  # Typical log scale for UVC exposure
                    "auto_prop": "CAP_PROP_AUTO_EXPOSURE",  # For UVC: 0.75=auto, 0.25=manual
                    "auto_on_value": 0.75,
                    "auto_off_value": 0.25,  # Generic UVC
                    "enabled": hasattr(cv2, "CAP_PROP_EXPOSURE")
                    and hasattr(cv2, "CAP_PROP_AUTO_EXPOSURE"),
                },
            }

        for control_name, config_from_profile in controls_to_query_from_profile.items():
            prop_data_for_ui = {
                "enabled": config_from_profile.get("enabled", False)
            }  # Default to not enabled if not specified

            # Get main VALUE (e.g., exposure time, brightness level)
            main_value_prop_str = config_from_profile.get(
                "prop"
            )  # Main property for the value
            # Some profiles might use "value_prop" if "prop" is used for something else in that control's context
            if not main_value_prop_str:
                main_value_prop_str = config_from_profile.get("value_prop")

            if main_value_prop_str and hasattr(cv2, main_value_prop_str):
                try:
                    val = self.cap.get(getattr(cv2, main_value_prop_str))
                    # Ensure val is not NaN or Inf which can break JSON/UI
                    if (
                        val is not None and cv2.ocl.useOpenCL()
                    ):  # Check for OpenCL issues with get sometimes
                        if isinstance(val, float) and (
                            val != val or val == float("inf") or val == float("-inf")
                        ):  # NaN or Inf
                            log.warning(
                                f"OpenCV property get for {main_value_prop_str} returned invalid float: {val}. Assuming 0."
                            )
                            val = 0.0  # Default to 0 if problematic value
                    prop_data_for_ui["value"] = val
                    prop_data_for_ui["enabled"] = (
                        True  # If we can get it, assume control is somewhat enabled
                    )
                except Exception as e_get_main_prop:
                    log.warning(
                        f"Could not get main property {main_value_prop_str} for {control_name}: {e_get_main_prop}"
                    )
                    prop_data_for_ui["enabled"] = (
                        False  # Cannot get value, disable related UI
                    )

            # Get AUTO MODE status (e.g., for exposure)
            auto_mode_prop_str = config_from_profile.get("auto_prop")
            if (
                auto_mode_prop_str
                and hasattr(cv2, auto_mode_prop_str)
                and prop_data_for_ui["enabled"]
            ):  # Only if main control is enabled
                try:
                    current_auto_mode_val = self.cap.get(
                        getattr(cv2, auto_mode_prop_str)
                    )
                    auto_on_val_from_profile = config_from_profile.get("auto_on_value")
                    # auto_off_val_from_profile = config_from_profile.get("auto_off_value") # Not directly used for "is_auto_on" check here

                    if auto_on_val_from_profile is not None:
                        # Check if current mode is close to the profile's "auto_on_value"
                        prop_data_for_ui["is_auto_on"] = (
                            abs(current_auto_mode_val - auto_on_val_from_profile) < 1e-3
                        )
                    # If auto_on_val not in profile, cannot reliably determine "is_auto_on" from profile.
                    # Could add generic UVC check here as fallback if control_name is 'exposure'.
                    elif (
                        control_name == "exposure"
                        and abs(current_auto_mode_val - 0.75) < 1e-3
                    ):  # Generic UVC auto exposure
                        prop_data_for_ui["is_auto_on"] = True
                    else:
                        prop_data_for_ui["is_auto_on"] = False  # Default if unsure
                except Exception as e_get_auto_prop:
                    log.warning(
                        f"Could not get auto_prop {auto_mode_prop_str} for {control_name}: {e_get_auto_prop}"
                    )
                    prop_data_for_ui["is_auto_on"] = False  # Default if error

            # Add range (min/max) and default from profile for UI sliders
            # These correspond to the main "value" of the control.
            # Profile uses "min", "max", "default" (for value).
            # Convert s values for exposure to ms if UI slider expects that, or adjust profile.
            # For now, assume profile values are what UI expects.
            for key in [
                "min",
                "max",
                "default_value",
                "label",
                "step",
            ]:  # "default" in profile -> "default_value" for UI
                profile_key = "default" if key == "default_value" else key
                if profile_key in config_from_profile:
                    prop_data_for_ui[key] = config_from_profile[profile_key]

            if prop_data_for_ui[
                "enabled"
            ]:  # Only add to payload if control is considered enabled
                properties_payload["controls"][control_name] = prop_data_for_ui

        log.debug(
            f"Queried camera properties payload for UI: {json.dumps(properties_payload, indent=2)}"
        )
        self.camera_properties_updated.emit(properties_payload)

    def _on_thread_frame(self, qimage: QImage, bgr_frame):
        """
        qimage: downscaled RGB image for display
        full_frame: full-res BGR numpy array for measurements/recording
        """
        # 1) Display only the downscaled pixmap
        pix = QPixmap.fromImage(qimage)
        self._last_pixmap_displayed = pix
        self._update_displayed_pixmap()

        # now forward the real BGR frame so the recorder can write it
        self.frame_ready.emit(qimage, bgr_frame)



    def closeEvent(self, event):
        log.info("QtCameraWidget closeEvent called.")
        if self._camera_thread:
            self._camera_thread.stop()
            self._camera_thread = None
        if self.cap:
            log.info(f"Releasing camera ID: {self.camera_id} during closeEvent.")
            self.cap.release()
            self.cap = None
        super().closeEvent(event)

