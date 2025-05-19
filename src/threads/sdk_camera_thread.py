import logging
import time
import imagingcontrol4 as ic4

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

from imagingcontrol4.properties import (
    PropInteger,
    PropFloat,
    PropBoolean,
    PropEnumeration,  # PropEnumeration is imported
    PropEnumEntry,  # Import this if needed, though often not directly instantiated by user
)

log = logging.getLogger(__name__)


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

    def request_stop(self):
        log.debug("Stop requested for SDKCameraThread")
        self._stop_requested = True

    def update_exposure(self, exp_us: int):
        log.debug(f"SDKCameraThread: Queuing exposure update: {exp_us} us")
        self._pending_exposure_us = exp_us

    def update_gain(self, gain_db: float):
        log.debug(f"SDKCameraThread: Queuing gain update: {gain_db} dB")
        self._pending_gain_db = gain_db

    def update_auto_exposure(self, auto: bool):
        log.debug(f"SDKCameraThread: Queuing auto exposure update: {auto}")
        self._pending_auto_exposure = auto

    def update_roi(self, x: int, y: int, w: int, h: int):
        log.debug(f"SDKCameraThread: Queuing ROI update: x={x},y={y},w={w},h={h}")
        self._pending_roi = (x, y, w, h)

    def _apply_pending_properties(self):
        if not self.pm or not self.grabber or not self.grabber.is_device_open:
            return

        if self._pending_auto_exposure is not None:
            try:
                auto_exp_prop = self.pm.find(ic4.PropId.EXPOSURE_AUTO)
                if (
                    auto_exp_prop.is_available
                    and auto_exp_prop.value != self._pending_auto_exposure
                ):
                    self.pm.set_value(
                        ic4.PropId.EXPOSURE_AUTO, self._pending_auto_exposure
                    )
                    log.info(f"Set EXPOSURE_AUTO to {self._pending_auto_exposure}")
                    if not self._pending_auto_exposure:
                        self._emit_camera_properties()
            except ic4.IC4Exception as e:
                log.warning(f"Failed to set EXPOSURE_AUTO: {e}")
            except (
                Exception
            ) as e:  # Catch other AttributeErrors if property not found/available
                log.warning(f"Generic error setting EXPOSURE_AUTO: {e}")
            self._pending_auto_exposure = None

        if self._pending_exposure_us is not None:
            try:
                auto_exp_prop = self.pm.find(ic4.PropId.EXPOSURE_AUTO)
                if auto_exp_prop.is_available and not auto_exp_prop.value:
                    self.pm.set_value(ic4.PropId.EXPOSURE, self._pending_exposure_us)
                    log.info(f"Set EXPOSURE to {self._pending_exposure_us} us")
                elif (
                    not auto_exp_prop.is_available
                ):  # If auto exposure not available, try setting manual
                    self.pm.set_value(ic4.PropId.EXPOSURE, self._pending_exposure_us)
                    log.info(
                        f"Set EXPOSURE to {self._pending_exposure_us} us (auto not available)."
                    )
                else:
                    log.info("Auto exposure is ON, not setting manual exposure.")
            except ic4.IC4Exception as e:
                log.warning(f"Failed to set EXPOSURE: {e}")
            except Exception as e:
                log.warning(f"Generic error setting EXPOSURE: {e}")
            self._pending_exposure_us = None

        if self._pending_gain_db is not None:
            try:
                self.pm.set_value(ic4.PropId.GAIN, self._pending_gain_db)
                log.info(f"Set GAIN to {self._pending_gain_db} dB")
            except ic4.IC4Exception as e:
                log.warning(f"Failed to set GAIN: {e}")
            except Exception as e:
                log.warning(f"Generic error setting GAIN: {e}")
            self._pending_gain_db = None

        if self._pending_roi is not None:
            x, y, w, h = self._pending_roi
            try:
                current_w_cam = self.pm.find(ic4.PropId.WIDTH).value
                current_h_cam = self.pm.find(ic4.PropId.HEIGHT).value

                if w > 0 and h > 0 and (w != current_w_cam or h != current_h_cam):
                    log.warning(
                        f"ROI size change (req: {w}x{h}, curr: {current_w_cam}x{current_h_cam}) requires camera restart. Not applying on-the-fly."
                    )
                elif w == 0 and h == 0:
                    self.pm.set_value(ic4.PropId.OFFSET_X, 0)
                    self.pm.set_value(ic4.PropId.OFFSET_Y, 0)
                    log.info(f"Reset OFFSET_X and OFFSET_Y to 0.")
                else:
                    if self.pm.is_property_available(
                        ic4.PropId.OFFSET_X
                    ) and self.pm.is_property_writable(ic4.PropId.OFFSET_X):
                        self.pm.set_value(ic4.PropId.OFFSET_X, x)
                        log.info(f"Set OFFSET_X={x}")
                    if self.pm.is_property_available(
                        ic4.PropId.OFFSET_Y
                    ) and self.pm.is_property_writable(ic4.PropId.OFFSET_Y):
                        self.pm.set_value(ic4.PropId.OFFSET_Y, y)
                        log.info(f"Set OFFSET_Y={y}")
            except ic4.IC4Exception as e:
                log.warning(f"Failed to set ROI properties: {e}")
            except Exception as e:
                log.warning(f"Generic error setting ROI: {e}")
            self._pending_roi = None

    def _emit_camera_properties(self):
        if not self.pm:
            self.camera_properties_updated.emit({})
            return

        props_dict = {"controls": {}, "roi": {}}
        prop_map_ids = {
            "exposure": (ic4.PropId.EXPOSURE, ic4.PropId.EXPOSURE_AUTO),
            "gain": (ic4.PropId.GAIN, None),
        }

        for name, (val_pid, auto_pid) in prop_map_ids.items():
            try:
                p_info = {"enabled": False}  # Default to disabled
                if self.pm.is_property_available(val_pid):
                    prop_val = self.pm.find(val_pid)
                    p_info["enabled"] = (
                        prop_val.is_writable
                    )  # Use is_writable for enabled status
                    if isinstance(prop_val, (PropInteger, PropFloat)):
                        p_info["min"] = prop_val.minimum
                        p_info["max"] = prop_val.maximum
                        p_info["value"] = prop_val.value
                    elif isinstance(prop_val, PropEnumeration):
                        # For enums, .value is the current selection string
                        p_info["options"] = [
                            str(entry.name) for entry in prop_val.Entries
                        ]
                        p_info["value"] = prop_val.value

                    if auto_pid and self.pm.is_property_available(auto_pid):
                        prop_auto = self.pm.find(auto_pid)
                        if prop_auto.is_available:
                            p_info["is_auto_on"] = bool(prop_auto.value)
                            p_info["auto_available"] = True
                            # if auto is on, the main value control might be disabled by UI
                            if (
                                p_info["is_auto_on"] and name == "exposure"
                            ):  # Specific for exposure
                                p_info["enabled"] = (
                                    False  # Disable manual exposure if auto is on
                                )
                        else:
                            p_info["auto_available"] = False
                props_dict["controls"][name] = p_info
            except (ic4.IC4Exception, AttributeError) as e:
                log.debug(f"Could not get property {name}: {e}")
                props_dict["controls"][name] = {
                    "enabled": False
                }  # Ensure disabled on error

        roi_props_dict = {}
        try:
            if self.pm.is_property_available(ic4.PropId.WIDTH):
                width_prop = self.pm.find(ic4.PropId.WIDTH)
                roi_props_dict["w"] = width_prop.value
                roi_props_dict["max_w"] = width_prop.maximum
            if self.pm.is_property_available(ic4.PropId.HEIGHT):
                height_prop = self.pm.find(ic4.PropId.HEIGHT)
                roi_props_dict["h"] = height_prop.value
                roi_props_dict["max_h"] = height_prop.maximum
            if self.pm.is_property_available(ic4.PropId.OFFSET_X):
                offset_x_prop = self.pm.find(ic4.PropId.OFFSET_X)
                roi_props_dict["x"] = offset_x_prop.value
                roi_props_dict["max_x"] = offset_x_prop.maximum
            if self.pm.is_property_available(ic4.PropId.OFFSET_Y):
                offset_y_prop = self.pm.find(ic4.PropId.OFFSET_Y)
                roi_props_dict["y"] = offset_y_prop.value
                roi_props_dict["max_y"] = offset_y_prop.maximum
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
            w = self.pm.find(ic4.PropId.WIDTH).value
            h = self.pm.find(ic4.PropId.HEIGHT).value
            pf_prop = self.pm.find(ic4.PropId.PIXEL_FORMAT)
            pf_val_str = pf_prop.value

            resolutions.append(f"{w}x{h} ({pf_val_str})")
        except ic4.IC4Exception as e:
            log.warning(f"Could not get current resolution details: {e}")
        except (
            AttributeError
        ) as e:  # Catch if .value is not found on a property (e.g. not available)
            log.warning(f"AttributeError getting resolution details: {e}")

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

            try:
                current_pf_prop = self.pm.find(ic4.PropId.PIXEL_FORMAT)
                current_pf_val = current_pf_prop.value

                log.info(f"Current camera pixel format: {current_pf_val}")
                desired_format_to_set = self.desired_pixel_format_str

                if (
                    self.desired_pixel_format_str
                    and current_pf_val != self.desired_pixel_format_str
                ):
                    if isinstance(current_pf_prop, PropEnumeration):
                        # --- THIS IS THE CORRECTED PART ---
                        available_formats = [
                            entry.name for entry in current_pf_prop.Entries
                        ]
                        # --- End of corrected part ---
                        log.info(
                            f"Available pixel formats on camera: {available_formats}"
                        )
                        if self.desired_pixel_format_str in available_formats:
                            desired_format_to_set = self.desired_pixel_format_str
                        elif "Mono 8" in available_formats:
                            desired_format_to_set = "Mono 8"
                            log.warning(
                                f"Desired format {self.desired_pixel_format_str} not found, falling back to 'Mono 8'"
                            )
                        elif (
                            "Mono8" in available_formats
                        ):  # Some cameras might use "Mono8"
                            desired_format_to_set = "Mono8"
                            log.warning(
                                f"Desired format {self.desired_pixel_format_str} not found, falling back to 'Mono8'"
                            )
                        else:
                            desired_format_to_set = current_pf_val
                            log.warning(
                                f"Neither desired format '{self.desired_pixel_format_str}' nor 'Mono 8'/'Mono8' found in options. Using camera current: {current_pf_val}"
                            )

                elif current_pf_val != "Mono 8" and current_pf_val != "Mono8":
                    if isinstance(current_pf_prop, PropEnumeration):
                        # Check both "Mono 8" and "Mono8" as they are common for TIS cameras
                        available_formats_check = [
                            entry.name for entry in current_pf_prop.Entries
                        ]
                        if "Mono 8" in available_formats_check:
                            desired_format_to_set = "Mono 8"
                        elif "Mono8" in available_formats_check:
                            desired_format_to_set = "Mono8"
                        else:
                            desired_format_to_set = current_pf_val  # Keep current if neither standard mono8 is available
                    elif not isinstance(current_pf_prop, PropEnumeration):
                        desired_format_to_set = "Mono 8"
                    else:
                        desired_format_to_set = current_pf_val

                if desired_format_to_set != current_pf_val:
                    self.pm.set_value(ic4.PropId.PIXEL_FORMAT, desired_format_to_set)
                    log.info(f"Set PIXEL_FORMAT to {desired_format_to_set}")

                self.current_pixel_format_name = self.pm.find(
                    ic4.PropId.PIXEL_FORMAT
                ).value
                # Accept "Mono 8" or "Mono8" for Grayscale8
                if self.current_pixel_format_name.replace(" ", "") == "Mono8":
                    self.actual_qimage_format = QImage.Format_Grayscale8
                else:
                    log.error(
                        f"Camera pixel format is {self.current_pixel_format_name}, not 'Mono 8' or 'Mono8'. Live view might fail."
                    )
                    self.camera_error.emit(
                        f"Unsupported format: {self.current_pixel_format_name}. Requires 'Mono 8' or 'Mono8'.",
                        "PixelFormatError",
                    )
                    return

            except ic4.IC4Exception as e:
                log.error(f"Error setting/getting PIXEL_FORMAT: {e}")
                self.camera_error.emit(f"Pixel Format Error: {e}", type(e).__name__)
                return
            except AttributeError as e:  # Catch if .Entries or .name is not found
                log.error(
                    f"AttributeError during pixel format setup (e.g. .Entries or .name missing): {e}"
                )
                self.camera_error.emit(
                    f"Pixel Format Enum Error: {e}", type(e).__name__
                )
                return

            try:
                if self.desired_width is not None and self.pm.is_property_writable(
                    ic4.PropId.WIDTH
                ):
                    self.pm.set_value(ic4.PropId.WIDTH, self.desired_width)
                if self.desired_height is not None and self.pm.is_property_writable(
                    ic4.PropId.HEIGHT
                ):
                    self.pm.set_value(ic4.PropId.HEIGHT, self.desired_height)

                self.current_frame_width = self.pm.find(ic4.PropId.WIDTH).value
                self.current_frame_height = self.pm.find(ic4.PropId.HEIGHT).value
                log.info(
                    f"Actual camera resolution: {self.current_frame_width}x{self.current_frame_height}"
                )
            except ic4.IC4Exception as e:
                log.warning(
                    f"Could not set/get WIDTH/HEIGHT: {e}. Using camera defaults."
                )
                self.current_frame_width = self.pm.find(ic4.PropId.WIDTH).value
                self.current_frame_height = self.pm.find(ic4.PropId.HEIGHT).value
            except AttributeError as e:
                log.warning(f"AttributeError setting/getting WIDTH/HEIGHT: {e}")

            try:
                if self.pm.is_property_available(
                    ic4.PropId.ACQUISITION_FRAME_RATE
                ) and self.pm.is_property_writable(ic4.PropId.ACQUISITION_FRAME_RATE):
                    self.pm.set_value(
                        ic4.PropId.ACQUISITION_FRAME_RATE, float(self.target_fps)
                    )
                    actual_fps = self.pm.find(ic4.PropId.ACQUISITION_FRAME_RATE).value
                    log.info(
                        f"Set ACQUISITION_FRAME_RATE to {self.target_fps}, actual: {actual_fps}"
                    )
            except ic4.IC4Exception as e:
                log.warning(f"Could not set frame rate: {e}")
            except AttributeError as e:
                log.warning(f"AttributeError setting frame rate: {e}")

            self._apply_pending_properties()
            self._emit_available_resolutions()
            self._emit_camera_properties()

            self.sink = ic4.QueueSink.create(accept_incomplete_frames=False)
            log.info(
                f"QueueSink created. Target format for sink: {self.current_pixel_format_name}"
            )

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
                    if e.code == ic4.ErrorCode.TIMEOUT:
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
                            f"Buffer received but QImage format is invalid. Current camera format: {self.current_pixel_format_name}"
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
            log.error(f"RuntimeError in camera thread: {e}")
            self.camera_error.emit(str(e), type(e).__name__)
        except ic4.IC4Exception as e:
            log.error(
                f"IC4Exception in camera thread: {e} (Code: {e.code if hasattr(e,'code') else 'N/A'})"
            )
            self.camera_error.emit(
                str(e), f"IC4Exception ({e.code if hasattr(e,'code') else 'N/A'})"
            )
        except (
            Exception
        ) as e:  # Catch-all for any other unhandled error in the run loop
            log.exception("Unhandled exception in camera thread run loop:")
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
