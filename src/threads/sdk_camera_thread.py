import logging
import time
import imagingcontrol4 as ic4

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

from imagingcontrol4.properties import (
    PropInteger,
    PropFloat,
    PropBoolean,
    PropEnumeration,
    PropEnumEntry,
)

log = logging.getLogger(__name__)

# Standard GenICam Property Names
PROP_WIDTH = "Width"
PROP_HEIGHT = "Height"
PROP_PIXEL_FORMAT = "PixelFormat"
PROP_EXPOSURE_TIME = "ExposureTime"
PROP_EXPOSURE_AUTO = "ExposureAuto"
PROP_GAIN = "Gain"
PROP_OFFSET_X = "OffsetX"
PROP_OFFSET_Y = "OffsetY"
PROP_ACQUISITION_FRAME_RATE = "AcquisitionFrameRate"


# --- Minimal Dummy Sink Listener ---
class DummySinkListener:
    def sink_connected(self, sink, image_type, min_buffers_required):
        log.debug(
            f"DummyListener: Sink connected. ImageType: {image_type}, MinBuffers: {min_buffers_required}"
        )
        # This handler should return True to allow streaming to start.
        return True

    def frames_queued(self, sink, userdata):
        # log.debug("DummyListener: Frames queued (event)") # Can be noisy
        pass

    def sink_lost(self, sink, userdata):
        log.warning("DummyListener: Sink lost!")
        pass


# --- End of Dummy Sink Listener ---


class SDKCameraThread(QThread):
    frame_ready = pyqtSignal(QImage, object)
    camera_resolutions_available = pyqtSignal(list)
    camera_properties_updated = pyqtSignal(dict)
    camera_error = pyqtSignal(str, str)

    def __init__(
        self,
        device_info: "ic4.DeviceInfo" = None,
        target_fps: float = 20.0,
        desired_width: int = None,
        desired_height: int = None,
        desired_pixel_format: str = "Mono 8",
        parent=None,
    ):
        super().__init__(parent)
        self._stop_requested = False
        self.device_info = device_info
        self.target_fps = target_fps
        self.desired_width = desired_width
        self.desired_height = desired_height
        self.desired_pixel_format_str = desired_pixel_format

        self._pending_exposure_us = None
        self._pending_gain_db = None
        self._pending_auto_exposure = None
        self._pending_roi = None

        self.grabber = None
        self.sink = None
        self.pm = None

        self.current_frame_width = 0
        self.current_frame_height = 0
        self.current_pixel_format_name = ""
        self.actual_qimage_format = QImage.Format_Invalid

        self.dummy_listener = DummySinkListener()  # Create an instance of the listener

    def request_stop(self):
        log.debug("Stop requested for SDKCameraThread")
        self._stop_requested = True

    def update_exposure(self, exp_us: int):
        self._pending_exposure_us = float(exp_us)

    def update_gain(self, gain_db: float):
        self._pending_gain_db = gain_db

    def update_auto_exposure(self, auto: bool):
        self._pending_auto_exposure = auto

    def update_roi(self, x: int, y: int, w: int, h: int):
        self._pending_roi = (x, y, w, h)

    def _is_prop_writable(self, prop_object):
        if prop_object and prop_object.is_available:
            if hasattr(prop_object, "is_readonly"):
                return not prop_object.is_readonly
            else:
                log.warning(
                    f"Property '{getattr(prop_object,'name', 'UnknownProp')}' lacks 'is_readonly' attribute. Assuming writable if available."
                )
                return True
        return False

    def _set_property_value(self, prop_name: str, value_to_set):
        try:
            prop = self.pm.find(prop_name)
            if self._is_prop_writable(prop):
                self.pm.set_value(prop_name, value_to_set)
                log.info(f"Set {prop.name} to {value_to_set}")
                return True
            elif prop and prop.is_available:
                log.warning(
                    f"Property {prop.name} found but not writable (is_readonly={getattr(prop, 'is_readonly', 'N/A')})."
                )
        except ic4.IC4Exception as e:
            log.warning(f"IC4Exception setting {prop_name} to {value_to_set}: {e}")
        except AttributeError as e:
            log.warning(
                f"AttributeError for {prop_name} during set (e.g. find failed or property attribute missing): {e}"
            )
        except Exception as e:
            log.warning(f"Generic error setting {prop_name} to {value_to_set}: {e}")
        return False

    def _apply_pending_properties(self):
        if not self.pm or not self.grabber or not self.grabber.is_device_open:
            return

        if self._pending_auto_exposure is not None:
            auto_value_to_set_str = (
                "Continuous" if self._pending_auto_exposure else "Off"
            )
            auto_value_to_set_bool = self._pending_auto_exposure

            prop_auto_exp = self.pm.find(PROP_EXPOSURE_AUTO)

            if prop_auto_exp and prop_auto_exp.is_available:
                success = False
                if isinstance(prop_auto_exp, PropEnumeration):
                    success = self._set_property_value(
                        PROP_EXPOSURE_AUTO, auto_value_to_set_str
                    )
                elif isinstance(prop_auto_exp, PropBoolean):
                    success = self._set_property_value(
                        PROP_EXPOSURE_AUTO, auto_value_to_set_bool
                    )
                else:
                    log.warning(
                        f"Property {PROP_EXPOSURE_AUTO} is not Enum or Bool, type: {type(prop_auto_exp)}. Attempting to set as string '{auto_value_to_set_str}'."
                    )
                    success = self._set_property_value(
                        PROP_EXPOSURE_AUTO, auto_value_to_set_str
                    )

                if success and not self._pending_auto_exposure:
                    self._emit_camera_properties()
            else:
                log.warning(f"Property {PROP_EXPOSURE_AUTO} not available for update.")
            self._pending_auto_exposure = None

        if self._pending_exposure_us is not None:
            prop_auto = self.pm.find(PROP_EXPOSURE_AUTO)
            is_auto_on = False
            if prop_auto and prop_auto.is_available:
                current_auto_val = prop_auto.value
                if isinstance(current_auto_val, str):
                    is_auto_on = current_auto_val != "Off"
                elif isinstance(current_auto_val, bool):
                    is_auto_on = current_auto_val

            if not is_auto_on:
                self._set_property_value(PROP_EXPOSURE_TIME, self._pending_exposure_us)
            else:
                log.info("Auto exposure is ON, not setting manual exposure time.")
            self._pending_exposure_us = None

        if self._pending_gain_db is not None:
            self._set_property_value(PROP_GAIN, self._pending_gain_db)
            self._pending_gain_db = None

        if self._pending_roi is not None:
            x, y, w, h = self._pending_roi
            prop_w_cam_obj = self.pm.find(PROP_WIDTH)
            prop_h_cam_obj = self.pm.find(PROP_HEIGHT)
            current_w_cam = (
                prop_w_cam_obj.value
                if prop_w_cam_obj and prop_w_cam_obj.is_available
                else 0
            )
            current_h_cam = (
                prop_h_cam_obj.value
                if prop_h_cam_obj and prop_h_cam_obj.is_available
                else 0
            )

            if w > 0 and h > 0 and (w != current_w_cam or h != current_h_cam):
                log.warning(
                    f"SDKCameraThread: ROI size change (req: {w}x{h}, curr: {current_w_cam}x{current_h_cam}) requested. "
                    "This should be handled by restarting the camera with new dimensions."
                )

            if x == 0 and y == 0 and w == 0 and h == 0:
                self._set_property_value(PROP_OFFSET_X, 0)
                self._set_property_value(PROP_OFFSET_Y, 0)
            else:
                self._set_property_value(PROP_OFFSET_X, x)
                self._set_property_value(PROP_OFFSET_Y, y)
            self._pending_roi = None

    def _emit_camera_properties(self):
        if not self.pm:
            self.camera_properties_updated.emit({})
            return

        props_dict = {"controls": {}, "roi": {}}
        prop_name_map = {
            "exposure": (PROP_EXPOSURE_TIME, PROP_EXPOSURE_AUTO),
            "gain": (PROP_GAIN, None),
        }

        for name, (val_prop_name, auto_prop_name) in prop_name_map.items():
            try:
                p_info = {"enabled": False, "value": 0, "min": 0, "max": 0}
                prop_val = self.pm.find(val_prop_name)

                if prop_val and prop_val.is_available:
                    p_info["enabled"] = self._is_prop_writable(prop_val)
                    if isinstance(prop_val, (PropInteger, PropFloat)):
                        p_info["min"] = prop_val.minimum
                        p_info["max"] = prop_val.maximum
                        p_info["value"] = prop_val.value
                    elif isinstance(prop_val, PropEnumeration):
                        try:
                            p_info["options"] = [
                                entry.name for entry in prop_val.entries
                            ]
                        except AttributeError:
                            p_info["options"] = [
                                str(entry) for entry in prop_val.entries
                            ]
                        p_info["value"] = prop_val.value

                    if auto_prop_name:
                        prop_auto = self.pm.find(auto_prop_name)
                        if prop_auto and prop_auto.is_available:
                            p_info["auto_available"] = True
                            current_auto_val = prop_auto.value
                            is_auto_mode_on = False
                            if isinstance(current_auto_val, str):
                                is_auto_mode_on = current_auto_val != "Off"
                            elif isinstance(current_auto_val, bool):
                                is_auto_mode_on = current_auto_val

                            p_info["is_auto_on"] = is_auto_mode_on

                            if p_info["is_auto_on"] and name == "exposure":
                                p_info["enabled"] = False
                        else:
                            p_info["auto_available"] = False
                props_dict["controls"][name] = p_info
            except (ic4.IC4Exception, AttributeError) as e:
                log.debug(
                    f"Could not get property '{name}' (using '{val_prop_name}'): {e}"
                )
                props_dict["controls"][name] = {
                    "enabled": False,
                    "value": 0,
                    "min": 0,
                    "max": 0,
                }

        roi_props_dict = {}
        try:
            prop_w = self.pm.find(PROP_WIDTH)
            if prop_w and prop_w.is_available:
                roi_props_dict["w"] = prop_w.value
                roi_props_dict["max_w"] = prop_w.maximum
            prop_h = self.pm.find(PROP_HEIGHT)
            if prop_h and prop_h.is_available:
                roi_props_dict["h"] = prop_h.value
                roi_props_dict["max_h"] = prop_h.maximum
            prop_ox = self.pm.find(PROP_OFFSET_X)
            if prop_ox and prop_ox.is_available:
                roi_props_dict["x"] = prop_ox.value
                roi_props_dict["max_x"] = prop_ox.maximum
            prop_oy = self.pm.find(PROP_OFFSET_Y)
            if prop_oy and prop_oy.is_available:
                roi_props_dict["y"] = prop_oy.value
                roi_props_dict["max_y"] = prop_oy.maximum
            props_dict["roi"] = roi_props_dict
        except (ic4.IC4Exception, AttributeError) as e:
            log.debug(f"Could not get ROI properties: {e}")
            props_dict["roi"] = {"max_w": 0, "max_h": 0}

        log.debug(f"Emitting camera_properties_updated: {props_dict}")
        self.camera_properties_updated.emit(props_dict)

    def _emit_available_resolutions(self):
        if not self.pm:
            self.camera_resolutions_available.emit([])
            return

        resolutions = []
        try:
            prop_w = self.pm.find(PROP_WIDTH)
            prop_h = self.pm.find(PROP_HEIGHT)
            prop_pf = self.pm.find(PROP_PIXEL_FORMAT)

            if (
                prop_w
                and prop_w.is_available
                and prop_h
                and prop_h.is_available
                and prop_pf
                and prop_pf.is_available
            ):
                w = prop_w.value
                h = prop_h.value
                pf_val_str = prop_pf.value
                resolutions.append(f"{w}x{h} ({pf_val_str})")
            else:
                log.warning(
                    "Could not retrieve all components (W,H,PF) for current resolution."
                )

        except (ic4.IC4Exception, AttributeError) as e:
            log.warning(f"Error getting resolution details: {e}")

        log.debug(f"Emitting camera_resolutions_available: {resolutions}")
        self.camera_resolutions_available.emit(resolutions)

    def run(self):
        log.info(
            f"SDKCameraThread started for device: {self.device_info.model_name if self.device_info else 'Unknown'}, "
            f"Desired WxH: {self.desired_width}x{self.desired_height}, Format: {self.desired_pixel_format_str}, FPS: {self.target_fps}"
        )
        self.grabber = ic4.Grabber()

        try:
            if not self.device_info:
                devices = ic4.DeviceEnum.devices()
                if not devices:
                    raise RuntimeError("No TIS cameras found.")
                self.device_info = devices[0]
                log.info(
                    f"No device_info provided, selected first: {self.device_info.model_name} (S/N {self.device_info.serial})"
                )

            self.grabber.device_open(self.device_info)
            log.info(f"Device opened: {self.device_info.model_name}")
            self.pm = self.grabber.device_property_map

            # --- Pixel Format Configuration ---
            try:
                current_pf_prop = self.pm.find(PROP_PIXEL_FORMAT)
                if not (current_pf_prop and current_pf_prop.is_available):
                    raise RuntimeError(
                        f"PixelFormat property ('{PROP_PIXEL_FORMAT}') not available."
                    )
                current_pf_val = current_pf_prop.value

                log.info(f"Current camera pixel format: {current_pf_val}")
                desired_format_to_set = self.desired_pixel_format_str

                if (
                    self.desired_pixel_format_str
                    and current_pf_val != self.desired_pixel_format_str
                ):
                    if isinstance(current_pf_prop, PropEnumeration):
                        available_formats = [
                            entry.name for entry in current_pf_prop.entries
                        ]
                        log.info(
                            f"Available pixel formats on camera: {available_formats}"
                        )
                        if self.desired_pixel_format_str in available_formats:
                            desired_format_to_set = self.desired_pixel_format_str
                        elif "Mono 8" in available_formats:
                            desired_format_to_set = "Mono 8"
                        elif "Mono8" in available_formats:
                            desired_format_to_set = "Mono8"
                        else:
                            desired_format_to_set = current_pf_val
                            log.warning(
                                f"Neither desired '{self.desired_pixel_format_str}' nor 'Mono 8'/'Mono8' found. Using current: {current_pf_val}"
                            )

                elif current_pf_val.replace(" ", "").lower() != "mono8":
                    if isinstance(current_pf_prop, PropEnumeration):
                        available_formats_check = [
                            entry.name for entry in current_pf_prop.entries
                        ]
                        if "Mono 8" in available_formats_check:
                            desired_format_to_set = "Mono 8"
                        elif "Mono8" in available_formats_check:
                            desired_format_to_set = "Mono8"
                        else:
                            desired_format_to_set = current_pf_val
                    elif self._is_prop_writable(current_pf_prop):
                        desired_format_to_set = "Mono 8"
                    else:
                        desired_format_to_set = current_pf_val

                if desired_format_to_set != current_pf_val:
                    self._set_property_value(PROP_PIXEL_FORMAT, desired_format_to_set)
                    self.current_pixel_format_name = self.pm.find(
                        PROP_PIXEL_FORMAT
                    ).value
                else:
                    self.current_pixel_format_name = current_pf_val

                if self.current_pixel_format_name.replace(" ", "") == "Mono8":
                    self.actual_qimage_format = QImage.Format_Grayscale8
                else:
                    log.error(
                        f"Final pixel format is {self.current_pixel_format_name}, not 'Mono 8'/'Mono8'. Live view might fail."
                    )
                    self.camera_error.emit(
                        f"Unsupported format: {self.current_pixel_format_name}. Requires 'Mono 8' or 'Mono8'.",
                        "PixelFormatError",
                    )
                    return

            except Exception as e:
                log.error(
                    f"Critical error during pixel format setup: {e}", exc_info=True
                )
                self.camera_error.emit(
                    f"Pixel Format Setup Error: {e}", type(e).__name__
                )
                return

            # --- Width/Height Configuration ---
            try:
                prop_w = self.pm.find(PROP_WIDTH)
                prop_h = self.pm.find(PROP_HEIGHT)

                if self.desired_width is not None and self._is_prop_writable(prop_w):
                    self.pm.set_value(PROP_WIDTH, self.desired_width)
                if self.desired_height is not None and self._is_prop_writable(prop_h):
                    self.pm.set_value(PROP_HEIGHT, self.desired_height)

                self.current_frame_width = (
                    prop_w.value
                    if prop_w and prop_w.is_available
                    else DEFAULT_FRAME_SIZE[0]
                )
                self.current_frame_height = (
                    prop_h.value
                    if prop_h and prop_h.is_available
                    else DEFAULT_FRAME_SIZE[1]
                )
                log.info(
                    f"Actual camera resolution: {self.current_frame_width}x{self.current_frame_height}"
                )
            except Exception as e:
                log.warning(f"Error setting/getting WIDTH/HEIGHT: {e}", exc_info=True)
                try:
                    prop_w_fallback = self.pm.find(PROP_WIDTH)
                    prop_h_fallback = self.pm.find(PROP_HEIGHT)
                    self.current_frame_width = (
                        prop_w_fallback.value
                        if prop_w_fallback and prop_w_fallback.is_available
                        else DEFAULT_FRAME_SIZE[0]
                    )
                    self.current_frame_height = (
                        prop_h_fallback.value
                        if prop_h_fallback and prop_h_fallback.is_available
                        else DEFAULT_FRAME_SIZE[1]
                    )
                except Exception as e_fallback:
                    log.error(f"Failed to read W/H even as fallback: {e_fallback}")
                    self.current_frame_width, self.current_frame_height = (
                        DEFAULT_FRAME_SIZE
                    )

            # --- Frame Rate Configuration ---
            try:
                prop_fps = self.pm.find(PROP_ACQUISITION_FRAME_RATE)
                if self._is_prop_writable(prop_fps):
                    self.pm.set_value(
                        PROP_ACQUISITION_FRAME_RATE, float(self.target_fps)
                    )
                    actual_fps = prop_fps.value
                    log.info(
                        f"Set ACQUISITION_FRAME_RATE to {self.target_fps}, actual: {actual_fps}"
                    )
                elif prop_fps and prop_fps.is_available:
                    log.warning(
                        f"'{PROP_ACQUISITION_FRAME_RATE}' found but not writable."
                    )
                else:
                    log.warning(f"'{PROP_ACQUISITION_FRAME_RATE}' not available.")
            except Exception as e:
                log.warning(f"Error setting frame rate: {e}", exc_info=True)

            self._apply_pending_properties()
            self._emit_available_resolutions()
            self._emit_camera_properties()

            # --- Corrected QueueSink instantiation ---
            self.sink = ic4.QueueSink(
                self.dummy_listener
            )  # Pass the dummy listener instance
            if hasattr(self.sink, "accept_incomplete_frames"):
                try:
                    self.sink.accept_incomplete_frames = False
                except Exception as e_sink_prop:
                    log.warning(
                        f"Could not set accept_incomplete_frames on QueueSink: {e_sink_prop}"
                    )
            # --- End of correction ---
            log.info(f"QueueSink created with dummy listener.")

            self.grabber.stream_setup(
                self.sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            log.info("Stream setup done with QueueSink.")
            self.grabber.stream_start()
            log.info("Streaming started.")

            last_frame_time = time.monotonic()

            while not self._stop_requested:
                self._apply_pending_properties()
                try:
                    buf = self.sink.pop(timeout_ms=100)
                except ic4.IC4Exception as e:
                    if hasattr(e, "code") and e.code == ic4.ErrorCode.TIMEOUT:
                        continue
                    else:
                        log.error(
                            f"IC4Exception during sink.pop: {e} (Code: {e.code if hasattr(e,'code') else 'N/A'})"
                        )
                        self.camera_error.emit(
                            str(e),
                            f"IC4ExceptionSinkPop ({e.code if hasattr(e,'code') else 'N/A'})",
                        )
                        break

                if buf is None:
                    continue

                try:
                    frame_width = buf.image_type.width
                    frame_height = buf.image_type.height
                    stride = buf.image_type.stride_bytes

                    if self.actual_qimage_format == QImage.Format_Invalid:
                        log.error(
                            f"Buffer received but QImage format is invalid (should be Grayscale8). Current camera format: {self.current_pixel_format_name}"
                        )
                        continue

                    qimg = QImage(
                        buf.mem_ptr,
                        frame_width,
                        frame_height,
                        stride,
                        self.actual_qimage_format,
                    )

                    if qimg.isNull():
                        log.warning("Created QImage is null.")
                    else:
                        self.frame_ready.emit(qimg.copy(), buf.mem_ptr)
                finally:
                    pass

                now = time.monotonic()
                dt = now - last_frame_time
                target_interval = 1.0 / self.target_fps if self.target_fps > 0 else 0.05
                if dt < target_interval:
                    sleep_duration_ms = int((target_interval - dt) * 1000)
                    if sleep_duration_ms > 5:
                        self.msleep(sleep_duration_ms)
                last_frame_time = time.monotonic()

        except RuntimeError as e:
            log.error(f"RuntimeError in camera thread: {e}", exc_info=True)
            self.camera_error.emit(str(e), type(e).__name__)
        except ic4.IC4Exception as e:
            log.error(
                f"IC4Exception in camera thread: {e} (Code: {e.code if hasattr(e,'code') else 'N/A'})",
                exc_info=True,
            )
            self.camera_error.emit(
                str(e), f"IC4Exception ({e.code if hasattr(e,'code') else 'N/A'})"
            )
        except Exception as e:
            log.exception("Unhandled exception in camera thread setup/run loop:")
            self.camera_error.emit(str(e), type(e).__name__)
        finally:
            log.info("Camera thread run() method finishing...")
            if self.grabber:
                if self.grabber.is_streaming:
                    try:
                        log.info("Stopping stream...")
                        self.grabber.stream_stop()
                    except ic4.IC4Exception as e:
                        log.error(f"Error stopping stream: {e}")
                if self.grabber.is_device_open:
                    try:
                        log.info("Closing device...")
                        self.grabber.device_close()
                    except ic4.IC4Exception as e:
                        log.error(f"Error closing device: {e}")
            self.grabber = None
            self.sink = None
            self.pm = None
            log.info(
                f"SDKCameraThread ({self.device_info.model_name if self.device_info else 'N/A'}) stopped."
            )
