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

# DEFAULT_FRAME_SIZE might be needed if reading current W/H fails catastrophically
from config import DEFAULT_FRAME_SIZE


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
PROP_ACQUISITION_MODE = "AcquisitionMode"
PROP_TRIGGER_MODE = "TriggerMode"


class DummySinkListener:
    def sink_connected(self, sink, image_type, min_buffers_required):
        log.debug(
            f"DummyListener: Sink connected. ImageType: {image_type}, MinBuffers: {min_buffers_required}"
        )
        return True

    def frames_queued(self, sink, userdata):
        pass

    def sink_disconnected(self, sink):
        log.debug(f"DummyListener: Sink disconnected (event for sink: {type(sink)}).")
        pass


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

        self.dummy_listener = DummySinkListener()

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
            elif prop and prop.is_available:  # Property found but not writable
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
                        f"Property {PROP_EXPOSURE_AUTO} is not Enum or Bool, type: {type(prop_auto_exp)}. Attempting set as string."
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
            prop_w_cam_obj, prop_h_cam_obj = self.pm.find(PROP_WIDTH), self.pm.find(
                PROP_HEIGHT
            )
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
                    f"SDKCameraThread: ROI size change (req: {w}x{h}, curr: {current_w_cam}x{current_h_cam}) requested. Restart camera for new dimensions."
                )

            if x == 0 and y == 0 and w == 0 and h == 0:  # Special case for reset
                self._set_property_value(PROP_OFFSET_X, 0)
                self._set_property_value(PROP_OFFSET_Y, 0)
                log.info("ROI reset request: Set OFFSET_X and OFFSET_Y to 0.")
            else:  # Apply offsets based on ROI x,y
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
                        p_info["min"], p_info["max"], p_info["value"] = (
                            prop_val.minimum,
                            prop_val.maximum,
                            prop_val.value,
                        )
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
                            is_auto_mode_on = (
                                (current_auto_val != "Off")
                                if isinstance(current_auto_val, str)
                                else bool(current_auto_val)
                            )
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
            for key, prop_name_str in [
                ("w", PROP_WIDTH),
                ("h", PROP_HEIGHT),
                ("x", PROP_OFFSET_X),
                ("y", PROP_OFFSET_Y),
            ]:
                prop = self.pm.find(prop_name_str)
                if prop and prop.is_available:
                    roi_props_dict[key] = prop.value
                    if hasattr(prop, "maximum"):
                        roi_props_dict[f"max_{key}"] = prop.maximum
            props_dict["roi"] = roi_props_dict
        except (ic4.IC4Exception, AttributeError) as e:
            log.debug(f"Could not get ROI properties: {e}")
            props_dict["roi"] = {}
        log.debug(f"Emitting camera_properties_updated: {props_dict}")
        self.camera_properties_updated.emit(props_dict)

    def _emit_available_resolutions(self):
        if not self.pm:
            self.camera_resolutions_available.emit([])
            return
        resolutions = []
        try:
            prop_w, prop_h, prop_pf = (
                self.pm.find(PROP_WIDTH),
                self.pm.find(PROP_HEIGHT),
                self.pm.find(PROP_PIXEL_FORMAT),
            )
            if (
                prop_w
                and prop_w.is_available
                and prop_h
                and prop_h.is_available
                and prop_pf
                and prop_pf.is_available
            ):
                resolutions.append(f"{prop_w.value}x{prop_h.value} ({prop_pf.value})")
            else:
                log.warning("Could not retrieve all components for current resolution.")
        except (ic4.IC4Exception, AttributeError) as e:
            log.warning(f"Error getting resolution details: {e}")
        log.debug(f"Emitting camera_resolutions_available: {resolutions}")
        self.camera_resolutions_available.emit(resolutions)

    def run(self):
        log.info(
            f"SDKCameraThread started for: {self.device_info.model_name if self.device_info else 'Unknown'}, WxH: {self.desired_width}x{self.desired_height}, Format: {self.desired_pixel_format_str}, FPS: {self.target_fps}"
        )
        self.grabber = ic4.Grabber()
        try:
            if not self.device_info:
                devices = ic4.DeviceEnum.devices()
                if not devices:
                    raise RuntimeError("No TIS cameras found.")
                self.device_info = devices[0]
                log.info(
                    f"Using first available TIS camera: {self.device_info.model_name}"
                )

            self.grabber.device_open(self.device_info)
            log.info(f"Device opened: {self.device_info.model_name}")
            self.pm = self.grabber.device_property_map

            # --- Configure critical properties BEFORE stream_setup ---
            try:
                # Pixel Format
                current_pf_prop = self.pm.find(PROP_PIXEL_FORMAT)
                if not (current_pf_prop and current_pf_prop.is_available):
                    raise RuntimeError(f"'{PROP_PIXEL_FORMAT}' not available.")
                current_pf_val = current_pf_prop.value
                log.info(f"Current pixel format: {current_pf_val}")
                desired_format_to_set = self.desired_pixel_format_str
                if (
                    self.desired_pixel_format_str
                    and current_pf_val != self.desired_pixel_format_str
                ):
                    if isinstance(current_pf_prop, PropEnumeration):
                        available_formats = [
                            entry.name for entry in current_pf_prop.entries
                        ]
                        log.info(f"Available pixel formats: {available_formats}")
                        if self.desired_pixel_format_str in available_formats:
                            desired_format_to_set = self.desired_pixel_format_str
                        elif "Mono 8" in available_formats:
                            desired_format_to_set = "Mono 8"
                        elif "Mono8" in available_formats:
                            desired_format_to_set = "Mono8"
                        else:
                            desired_format_to_set = current_pf_val
                            log.warning(
                                f"Desired/Fallback Mono8 not found. Using: {current_pf_val}"
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
                self.current_pixel_format_name = self.pm.find(PROP_PIXEL_FORMAT).value
                if self.current_pixel_format_name.replace(" ", "") == "Mono8":
                    self.actual_qimage_format = QImage.Format_Grayscale8
                else:
                    raise RuntimeError(
                        f"Final format {self.current_pixel_format_name} is not Mono8."
                    )

                # Width/Height
                prop_w, prop_h = self.pm.find(PROP_WIDTH), self.pm.find(PROP_HEIGHT)
                if self.desired_width is not None and self._is_prop_writable(prop_w):
                    self._set_property_value(PROP_WIDTH, self.desired_width)
                if self.desired_height is not None and self._is_prop_writable(prop_h):
                    self._set_property_value(PROP_HEIGHT, self.desired_height)
                self.current_frame_width = (
                    prop_w.value if prop_w and prop_w.is_available else 0
                )
                self.current_frame_height = (
                    prop_h.value if prop_h and prop_h.is_available else 0
                )
                if self.current_frame_width == 0 or self.current_frame_height == 0:
                    self.current_frame_width, self.current_frame_height = (
                        DEFAULT_FRAME_SIZE
                    )
                    log.warning(f"Used default frame size: {DEFAULT_FRAME_SIZE}")
                log.info(
                    f"Actual camera resolution: {self.current_frame_width}x{self.current_frame_height}"
                )

                # Acquisition Mode & FrameRate & TriggerMode
                log.info(
                    f"Setting AcquisitionMode=Continuous, TriggerMode=Off, FPS={self.target_fps}"
                )
                self._set_property_value(PROP_ACQUISITION_MODE, "Continuous")
                self._set_property_value(PROP_TRIGGER_MODE, "Off")

                prop_fps = self.pm.find(PROP_ACQUISITION_FRAME_RATE)
                if self._is_prop_writable(prop_fps):
                    self._set_property_value(
                        PROP_ACQUISITION_FRAME_RATE, float(self.target_fps)
                    )
                    log.info(
                        f"Set {PROP_ACQUISITION_FRAME_RATE}, actual: {prop_fps.value if prop_fps and prop_fps.is_available else 'N/A'}"
                    )
                elif prop_fps and prop_fps.is_available:
                    log.warning(f"'{PROP_ACQUISITION_FRAME_RATE}' not writable.")
                else:
                    log.warning(f"'{PROP_ACQUISITION_FRAME_RATE}' not available.")

            except Exception as e:
                log.error(
                    f"Critical property setup error (PixelFormat/W/H/AcqMode/Trigger/FPS): {e}",
                    exc_info=True,
                )
                self.camera_error.emit(f"Camera Config Error: {e}", type(e).__name__)
                return

            self._apply_pending_properties()
            self._emit_available_resolutions()
            self._emit_camera_properties()

            self.sink = ic4.QueueSink(self.dummy_listener)
            if hasattr(self.sink, "accept_incomplete_frames"):
                try:
                    self.sink.accept_incomplete_frames = False
                except Exception as e:
                    log.warning(f"Could not set accept_incomplete_frames: {e}")
            log.info("QueueSink created.")

            log.info("Pausing briefly before stream_setup with ACQUISITION_START...")
            time.sleep(0.2)

            self.grabber.stream_setup(
                self.sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            log.info(
                "Stream setup with ACQUISITION_START attempted, and acquisition should be starting."
            )

            log.info("Entering frame acquisition loop...")
            frame_counter = 0
            null_buffer_counter = 0
            last_frame_time = time.monotonic()

            while not self._stop_requested:
                self._apply_pending_properties()
                buf = None
                try:
                    # *** CORRECTED to use pop_output_buffer() with NO arguments ***
                    buf = self.sink.pop_output_buffer()
                except ic4.IC4Exception as e_pop:
                    if hasattr(e_pop, "code") and e_pop.code == ic4.ErrorCode.TIMEOUT:
                        null_buffer_counter += 1
                        if null_buffer_counter > 0 and null_buffer_counter % 100 == 0:
                            log.warning(
                                f"Still no frames after {null_buffer_counter/10.0:.1f}s of polling (pop_output_buffer timed out)."
                            )
                        continue  # Try again on next loop iteration
                    # For other IC4Exceptions from pop_output_buffer
                    log.error(
                        f"IC4Exception during pop_output_buffer (no-arg): {e_pop}",
                        exc_info=True,
                    )
                    self.camera_error.emit(
                        str(e_pop),
                        f"SinkPopNoArgErr ({e_pop.code if hasattr(e_pop,'code') else 'N/A'})",
                    )
                    break  # Exit loop on significant error
                except TypeError as te:
                    log.error(
                        f"TypeError calling pop_output_buffer() with no arguments: {te}. This should not happen if the previous error was correct."
                    )
                    self.camera_error.emit(str(te), "SinkPopNoArgSignatureError")
                    break
                except Exception as e_generic_pop:
                    log.error(
                        f"Generic Exception during pop_output_buffer (no-arg): {e_generic_pop}",
                        exc_info=True,
                    )
                    self.camera_error.emit(str(e_generic_pop), "SinkPopGenericError")
                    break

                if (
                    buf is None
                ):  # If pop_output_buffer() is non-blocking and returns None when no frame
                    null_buffer_counter += 1
                    if null_buffer_counter > 0 and null_buffer_counter % 100 == 0:
                        log.warning(
                            f"Still no frames after {null_buffer_counter/10.0:.1f}s of polling (buf is None from pop_output_buffer)."
                        )
                    self.msleep(10)  # Yield/sleep briefly if non-blocking and no frame
                    continue

                # If we reach here, buf should be a valid buffer
                frame_counter += 1
                log.info(
                    f"Frame {frame_counter}: Buffer received! W: {buf.image_type.width}, H: {buf.image_type.height}, Format: {buf.image_type.pixel_format.name}"
                )
                null_buffer_counter = 0  # Reset counter

                try:
                    qimg = QImage(
                        buf.mem_ptr,
                        buf.image_type.width,
                        buf.image_type.height,
                        buf.image_type.stride_bytes,
                        self.actual_qimage_format,
                    )
                    if qimg.isNull():
                        log.warning(f"Frame {frame_counter}: Created QImage is null.")
                    else:
                        log.debug(
                            f"Frame {frame_counter}: QImage created successfully, emitting frame_ready."
                        )
                        self.frame_ready.emit(qimg.copy(), buf.mem_ptr)
                finally:
                    pass

                now = time.monotonic()
                dt = now - last_frame_time
                target_interval = 1.0 / self.target_fps if self.target_fps > 0 else 0.05
                if dt < target_interval:
                    sleep_ms = int((target_interval - dt) * 1000)
                    if sleep_ms > 5:
                        self.msleep(sleep_ms)
                last_frame_time = time.monotonic()
            log.info("Exited frame acquisition loop.")
        except Exception as e:
            log.exception("Unhandled exception in SDKCameraThread.run():")
            self.camera_error.emit(str(e), type(e).__name__)
        finally:
            log.info("SDKCameraThread run() finishing...")
            if self.grabber:
                is_streaming_flag = False
                try:
                    is_streaming_flag = self.grabber.is_streaming
                except:
                    pass

                if is_streaming_flag:
                    try:
                        self.grabber.stream_stop()
                        log.info("Stream stopped.")
                    except Exception as e:
                        log.error(f"Error stopping stream: {e}")

                is_open_flag = False
                try:
                    is_open_flag = self.grabber.is_device_open
                except:
                    pass

                if is_open_flag:
                    try:
                        self.grabber.device_close()
                        log.info("Device closed.")
                    except Exception as e:
                        log.error(f"Error closing device: {e}")
            self.grabber, self.sink, self.pm = None, None, None
            log.info(
                f"SDKCameraThread ({self.device_info.model_name if self.device_info else 'N/A'}) fully stopped."
            )
