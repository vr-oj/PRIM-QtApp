import cv2
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy
from PyQt5.QtCore import QTimer, pyqtSignal, Qt, QSize, pyqtSlot
from PyQt5.QtGui import QImage, QPixmap, QFont
import logging
import json
import os

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
    frame_ready = pyqtSignal(QImage, object) # QImage for display, object (BGR frame) for recording
    camera_error = pyqtSignal(str, int)
    camera_resolutions_updated = pyqtSignal(list)
    camera_properties_updated = pyqtSignal(dict)

    def __init__(self, camera_id: int = -1, camera_description: str = "", parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumSize(320, 240) # Adjusted minimum size
        # QSS Suggestion: QtCameraWidget { background-color: #yourCameraBg; border: 1px solid #yourBorderColor; }

        self.viewfinder_label = QLabel(self)
        self.viewfinder_label.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(12)
        self.viewfinder_label.setFont(font)
        self.viewfinder_label.setScaledContents(False) # Important for quality when scaling pixmap
        self.viewfinder_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

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
        # REMOVED: self._last_pixmap_displayed = None

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._grab_frame)

        self.load_camera_profile()
        self._update_placeholder_text()

    def _update_placeholder_text(self, message=None):
        if self.cap and self.cap.isOpened():
            self.viewfinder_label.setText("")
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
        if not (self.cap and self.cap.isOpened()):
            self.viewfinder_label.setPixmap(QPixmap()) # Clear existing pixmap

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

    @pyqtSlot(int, str)
    def set_active_camera(self, camera_id: int, camera_description: str = ""):
        log.info(
            f"Attempting to set active camera to ID: {camera_id} ('{camera_description}')"
        )
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
                    log.warning(
                        f"Failed to open camera ID {self.camera_id} with CAP_DSHOW, trying default API."
                    )
                    self.cap = cv2.VideoCapture(self.camera_id)
                    if not self.cap.isOpened():
                        self.cap = None
                        error_msg = (
                            f"Cannot open camera ID: {self.camera_id} with any backend."
                        )
                        log.error(error_msg)
                        self.camera_error.emit(error_msg, -1)
                        self._update_placeholder_text(
                            f"Error: Could not open Camera {self.camera_id}.\nCheck connections or drivers."
                        )
                        self.camera_resolutions_updated.emit([])
                        self.camera_properties_updated.emit({})
                        return False

                log.info(
                    f"Successfully opened camera ID: {self.camera_id} ('{self.camera_description}')"
                )
                self._update_placeholder_text("")

                target_w, target_h = 0, 0
                if self.active_profile:
                    default_res_label = self.active_profile.get(
                        "default_resolution_label"
                    )
                    res_options = self.active_profile.get("resolutions", [])
                    found_default = False
                    if default_res_label:
                        for res_info in res_options:
                            if res_info.get("label") == default_res_label:
                                target_w, target_h = (
                                    res_info["width"],
                                    res_info["height"],
                                )
                                found_default = True
                                break
                    if not found_default and res_options:
                        res_info = res_options[0]
                        target_w, target_h = res_info["width"], res_info["height"]

                if target_w > 0 and target_h > 0:
                    log.info(
                        f"Setting camera {self.camera_id} resolution from profile to {target_w}x{target_h}"
                    )
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(target_w))
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(target_h))
                else:
                    log.info(
                        f"No profile resolution for {self.camera_id}, trying generic 1920x1080."
                    )
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920.0)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080.0)
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
                self.reset_roi_to_default()
                res_list_for_ui = []
                if self.active_profile and "resolutions" in self.active_profile:
                    for r_info in self.active_profile["resolutions"]:
                        res_list_for_ui.append(f"{r_info['width']}x{r_info['height']}")
                    self.camera_resolutions_updated.emit(list(set(res_list_for_ui)))
                else:
                    self.camera_resolutions_updated.emit(
                        [f"{self.full_frame_width}x{self.full_frame_height}"]
                    )
                self.query_and_emit_camera_properties()
                self.timer.start(max(15, 1000 // 60))
                return True

            except Exception as e:
                error_msg = (
                    f"Exception opening/configuring camera ID {self.camera_id}: {e}"
                )
                log.error(error_msg, exc_info=True)
                self.camera_error.emit(error_msg, -2)
                self._update_placeholder_text(
                    f"Exception with Camera {self.camera_id}.\nSee logs for details."
                )
                if self.cap: self.cap.release(); self.cap = None
                self.camera_resolutions_updated.emit([])
                self.camera_properties_updated.emit({})
                return False
        else:
            self._update_placeholder_text()
            self.camera_resolutions_updated.emit([])
            self.active_profile = None
            self.camera_properties_updated.emit({})
            return True

    @pyqtSlot(int, int)
    def set_active_resolution(self, width: int, height: int):
        if self.cap and self.cap.isOpened():
            log.info(
                f"Attempting to set resolution to {width}x{height} for camera ID: {self.camera_id}"
            )
            was_timing = self.timer.isActive()
            if was_timing: self.timer.stop()

            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
            actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            if actual_w == 0 or actual_h == 0:
                log.warning(
                    f"Failed to set {width}x{height}. Camera reported {actual_w}x{actual_h}."
                )
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
            if was_timing: self.timer.start(max(15, 1000 // 60))
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
            if self.full_frame_width <= 0 or self.full_frame_height <= 0:
                log.warning(
                    "Cannot calculate ROI from factors: full frame dimensions are invalid."
                )
                self.roi_x, self.roi_y, self.roi_w, self.roi_h = (0,0,0,0)
            else:
                self.roi_x = roi_profile.get("default_x", 0)
                self.roi_y = roi_profile.get("default_y", 0)
                w_factor = roi_profile.get("default_w_factor")
                h_factor = roi_profile.get("default_h_factor")
                if w_factor is not None and w_factor > 0:
                    self.roi_w = int(self.full_frame_width * w_factor)
                else:
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
        self.query_and_emit_camera_properties()

    def set_software_roi(self, x, y, w, h):
        # ... (logic seems okay, ensure logging and validation against current full_frame_width/height)
        if self.full_frame_width > 0 and self.full_frame_height > 0:
            self.roi_x = max(0, min(x, self.full_frame_width - 1))
            self.roi_y = max(0, min(y, self.full_frame_height - 1))
            self.roi_w = max(0, min(w, (self.full_frame_width - self.roi_x if w > 0 else self.full_frame_width - self.roi_x)))
            self.roi_h = max(0, min(h, (self.full_frame_height - self.roi_y if h > 0 else self.full_frame_height - self.roi_y)))
        else:
            self.roi_x, self.roi_y, self.roi_w, self.roi_h = x, y, w, h
        log.info(
            f"Software ROI set to x:{self.roi_x}, y:{self.roi_y}, w:{self.roi_w}, h:{self.roi_h}"
        )
        self.query_and_emit_camera_properties()

    def _grab_frame(self):
        if not (self.cap and self.cap.isOpened()):
            if self.timer.isActive(): self.timer.stop()
            self._update_placeholder_text(f"Camera {self.camera_id} not available.")
            return

        ret, full_frame = self.cap.read()
        if not ret or full_frame is None:
            log.warning(
                f"Failed to grab frame from camera ID: {self.camera_id}. Ret: {ret}"
            )
            return

        frame_to_process = full_frame
        use_roi_w = self.roi_w if self.roi_w > 0 else self.full_frame_width - self.roi_x
        use_roi_h = self.roi_h if self.roi_h > 0 else self.full_frame_height - self.roi_y

        if (use_roi_w > 0 and use_roi_h > 0 and
            (self.roi_x > 0 or self.roi_y > 0 or self.roi_w > 0 or self.roi_h > 0)):
            y1 = max(0, self.roi_y)
            y2 = min(self.roi_y + use_roi_h, self.full_frame_height)
            x1 = max(0, self.roi_x)
            x2 = min(self.roi_x + use_roi_w, self.full_frame_width)
            if y2 > y1 and x2 > x1:
                frame_to_process = full_frame[y1:y2, x1:x2]
            else:
                log.debug("ROI resulted in zero or negative size, using full frame.")
                frame_to_process = full_frame

        if (frame_to_process is None or frame_to_process.shape[0] == 0 or
            frame_to_process.shape[1] == 0):
            log.warning("Frame to display has zero height or width after ROI. Skipping display.")
            return

        bgr_frame_for_recording = frame_to_process.copy()

        try:
            rgb_frame = cv2.cvtColor(frame_to_process, cv2.COLOR_BGR2RGB)
        except cv2.error as e:
            log.error(f"OpenCV error during BGR2RGB conversion: {e}. Frame shape: {frame_to_process.shape}")
            return

        h, w, ch = rgb_frame.shape
        bytes_per_line = ch * w
        qimg = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format_RGB888)

        # DO NOT UPDATE UI FROM HERE
        # self._last_pixmap_displayed = QPixmap.fromImage(qimg)
        # self._update_displayed_pixmap()

        self.frame_ready.emit(qimg.copy(), bgr_frame_for_recording)

    # REMOVED: _update_displayed_pixmap method

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # The scaling of the pixmap will be handled by MainWindow._on_frame_ready
        # This event ensures the label itself resizes. The next frame received
        # by MainWindow will be scaled to the new label size.

    def get_current_resolution(self):
        if self.cap and self.cap.isOpened():
            if self.full_frame_width > 0 and self.full_frame_height > 0:
                return QSize(self.full_frame_width, self.full_frame_height)
            else:
                width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                if width > 0 and height > 0: return QSize(width, height)
        return QSize()

    def _get_cv2_prop_from_profile(self, control_key: str, prop_name_in_config: str = "prop"):
        # ... (no changes needed)
        if self.active_profile and "controls" in self.active_profile:
            control_config = self.active_profile["controls"].get(control_key)
            if control_config and prop_name_in_config in control_config:
                return control_config[prop_name_in_config]
        return None

    def _set_camera_property(self, control_key: str, value: float, prop_name_in_config: str = "prop"):
        # ... (no changes needed)
        if not (self.cap and self.cap.isOpened()):
            log.warning(f"Cannot set {control_key}: Camera not open or not available.")
            return False

        prop_str = self._get_cv2_prop_from_profile(control_key, prop_name_in_config)

        if not prop_str:
            generic_map = {
                "brightness": "CAP_PROP_BRIGHTNESS", "gain": "CAP_PROP_GAIN",
                "exposure": "CAP_PROP_EXPOSURE", "auto_exposure_mode": "CAP_PROP_AUTO_EXPOSURE",
            }
            if prop_name_in_config == "prop": prop_str = generic_map.get(control_key)
            elif prop_name_in_config == "auto_prop" and control_key == "exposure":
                prop_str = generic_map.get("auto_exposure_mode")

        if prop_str and hasattr(cv2, prop_str):
            prop_id = getattr(cv2, prop_str)
            try:
                ret = self.cap.set(prop_id, float(value))
                actual_value = self.cap.get(prop_id)
                log.info(f"Set CamProp '{control_key}' (OpenCV {prop_str}={prop_id}) to {value}, success: {ret}. Actual val: {actual_value:.2f}")
                if not ret: log.warning(f"Failed to set {control_key} ({prop_str}) to {value} (cap.set returned False).")
                return ret
            except Exception as e_set_prop:
                log.error(f"Exception setting CamProp '{control_key}' ({prop_str}) to {value}: {e_set_prop}")
                return False
        else:
            log.warning(f"Property for '{control_key}' (config key:'{prop_name_in_config}', resolved OpenCV prop:'{prop_str}') not found in cv2 or profile.")
            return False

    @pyqtSlot(int)
    def set_brightness(self, value: int):
        if self._set_camera_property("brightness", float(value)): self.query_and_emit_camera_properties()

    @pyqtSlot(int)
    def set_gain(self, value: int):
        if self._set_camera_property("gain", float(value)): self.query_and_emit_camera_properties()

    @pyqtSlot(int)
    def set_exposure(self, value: int):
        # ... (no changes needed)
        if (self.active_profile and "controls" in self.active_profile and
            "exposure" in self.active_profile["controls"]):
            exp_config = self.active_profile["controls"]["exposure"]
            auto_prop_str = exp_config.get("auto_prop")
            auto_off_val = exp_config.get("auto_off_value")
            if (auto_prop_str and auto_off_val is not None and hasattr(cv2, auto_prop_str)):
                current_auto_mode = self.cap.get(getattr(cv2, auto_prop_str))
                if abs(current_auto_mode - auto_off_val) > 1e-3:
                    log.info(f"Exposure control: Auto-exposure seems ON (current mode {current_auto_mode}, profile manual_mode_val {auto_off_val}). Attempting to set manual mode first.")
        value_prop_config_key = ("value_prop" if self.active_profile and "value_prop" in
                                 self.active_profile.get("controls", {}).get("exposure", {}) else "prop")
        if self._set_camera_property("exposure", float(value), prop_name_in_config=value_prop_config_key):
            self.query_and_emit_camera_properties()


    @pyqtSlot(bool)
    def set_auto_exposure(self, enable_auto: bool):
        # ... (no changes needed)
        target_mode_value = None
        if (self.active_profile and "controls" in self.active_profile and
            "exposure" in self.active_profile["controls"]):
            exp_config = self.active_profile["controls"]["exposure"]
            if enable_auto: target_mode_value = exp_config.get("auto_on_value")
            else: target_mode_value = exp_config.get("auto_off_value")
        else: target_mode_value = 0.75 if enable_auto else 0.25

        if target_mode_value is not None:
            if self._set_camera_property("exposure", target_mode_value, prop_name_in_config="auto_prop"):
                self.query_and_emit_camera_properties()
        else:
            log.warning("Auto exposure on/off values not defined in profile for 'exposure' control's 'auto_prop'.")

    def query_and_emit_camera_properties(self):
        # ... (no changes needed, but ensure it's robust as before)
        if not (self.cap and self.cap.isOpened()):
            self.camera_properties_updated.emit({})
            return

        properties_payload = {
            "controls": {},
            "roi": { "x": self.roi_x, "y": self.roi_y, "w": self.roi_w, "h": self.roi_h,
                     "max_w": self.full_frame_width, "max_h": self.full_frame_height, },
        }
        controls_to_query_from_profile = {}
        if self.active_profile and "controls" in self.active_profile:
            controls_to_query_from_profile = self.active_profile["controls"]
        else:
            controls_to_query_from_profile = {
                "brightness": {"prop": "CAP_PROP_BRIGHTNESS", "min": 0, "max": 255, "enabled": hasattr(cv2, "CAP_PROP_BRIGHTNESS")},
                "gain": {"prop": "CAP_PROP_GAIN", "min": 0, "max": 100, "enabled": hasattr(cv2, "CAP_PROP_GAIN")},
                "exposure": {"prop": "CAP_PROP_EXPOSURE", "min": -13, "max": 0,
                             "auto_prop": "CAP_PROP_AUTO_EXPOSURE", "auto_on_value": 0.75, "auto_off_value": 0.25,
                             "enabled": hasattr(cv2, "CAP_PROP_EXPOSURE") and hasattr(cv2, "CAP_PROP_AUTO_EXPOSURE"),},
            }

        for control_name, config_from_profile in controls_to_query_from_profile.items():
            prop_data_for_ui = {"enabled": config_from_profile.get("enabled", False)}
            main_value_prop_str = config_from_profile.get("prop")
            if not main_value_prop_str: main_value_prop_str = config_from_profile.get("value_prop")

            if main_value_prop_str and hasattr(cv2, main_value_prop_str):
                try:
                    val = self.cap.get(getattr(cv2, main_value_prop_str))
                    if val is not None and cv2.ocl.useOpenCL():
                        if isinstance(val, float) and (val != val or val == float("inf") or val == float("-inf")):
                            log.warning(f"OpenCV property get for {main_value_prop_str} returned invalid float: {val}. Assuming 0.")
                            val = 0.0
                    prop_data_for_ui["value"] = val
                    prop_data_for_ui["enabled"] = True
                except Exception as e_get_main_prop:
                    log.warning(f"Could not get main property {main_value_prop_str} for {control_name}: {e_get_main_prop}")
                    prop_data_for_ui["enabled"] = False

            auto_mode_prop_str = config_from_profile.get("auto_prop")
            if auto_mode_prop_str and hasattr(cv2, auto_mode_prop_str) and prop_data_for_ui["enabled"]:
                try:
                    current_auto_mode_val = self.cap.get(getattr(cv2, auto_mode_prop_str))
                    auto_on_val_from_profile = config_from_profile.get("auto_on_value")
                    if auto_on_val_from_profile is not None:
                        prop_data_for_ui["is_auto_on"] = abs(current_auto_mode_val - auto_on_val_from_profile) < 1e-3
                    elif control_name == "exposure" and abs(current_auto_mode_val - 0.75) < 1e-3:
                        prop_data_for_ui["is_auto_on"] = True
                    else: prop_data_for_ui["is_auto_on"] = False
                except Exception as e_get_auto_prop:
                    log.warning(f"Could not get auto_prop {auto_mode_prop_str} for {control_name}: {e_get_auto_prop}")
                    prop_data_for_ui["is_auto_on"] = False

            for key in ["min", "max", "default_value", "label", "step"]:
                profile_key = "default" if key == "default_value" else key
                if profile_key in config_from_profile: prop_data_for_ui[key] = config_from_profile[profile_key]
            if prop_data_for_ui["enabled"]:
                properties_payload["controls"][control_name] = prop_data_for_ui
        log.debug(f"Queried camera properties payload for UI: {json.dumps(properties_payload, indent=2)}")
        self.camera_properties_updated.emit(properties_payload)


    def closeEvent(self, event):
        log.info("QtCameraWidget closeEvent called.")
        self.timer.stop()
        if self.cap:
            log.info(f"Releasing camera ID: {self.camera_id} during closeEvent.")
            self.cap.release()
            self.cap = None
        super().closeEvent(event)