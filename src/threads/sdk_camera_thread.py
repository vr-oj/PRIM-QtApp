import logging
import time  # Keep time import

# Change top-level import
import imagingcontrol4 as ic4

from PyQt5.QtCore import (
    QThread,
    pyqtSignal,
)  # QMutex, QWaitCondition not used here currently
from PyQt5.QtGui import QImage

# Properties module import remains the same if it's structured as a submodule
from imagingcontrol4.properties import (
    PropInteger,
    PropFloat,
    PropBoolean,
    PropEnumeration,
)

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    """
    Thread handling TIS SDK camera grab and emitting live frames and camera properties.
    Uses QueueSink for continuous streaming and frames with pop_buffer.
    """

    frame_ready = pyqtSignal(QImage, object)
    camera_resolutions_available = pyqtSignal(list)
    camera_properties_updated = pyqtSignal(dict)
    camera_error = pyqtSignal(str, str)

    def __init__(
        self,
        device_info: "ic4.DeviceInfo" = None,  # Use string literal for type hint if ic4 not fully available at parse time
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
        self.sink = None  # Will be ic4.QueueSink
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
                current_auto = self.pm.get_value(ic4.PropId.EXPOSURE_AUTO)
                if current_auto != self._pending_auto_exposure:
                    self.pm.set_value(
                        ic4.PropId.EXPOSURE_AUTO, self._pending_auto_exposure
                    )
                    log.info(f"Set EXPOSURE_AUTO to {self._pending_auto_exposure}")
                    if not self._pending_auto_exposure:
                        self._emit_camera_properties()
            except ic4.IC4Exception as e:
                log.warning(f"Failed to set EXPOSURE_AUTO: {e}")
            except Exception as e:
                log.warning(f"Generic error setting EXPOSURE_AUTO: {e}")
            self._pending_auto_exposure = None

        if self._pending_exposure_us is not None:
            try:
                is_auto_on = self.pm.get_value(ic4.PropId.EXPOSURE_AUTO)
                if not is_auto_on:
                    self.pm.set_value(ic4.PropId.EXPOSURE, self._pending_exposure_us)
                    log.info(f"Set EXPOSURE to {self._pending_exposure_us} us")
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
                # For QueueSink, ROI changes (especially size) generally require stream re-setup.
                # This simplified version will only attempt to set offsets if width/height match current.
                current_w_cam = self.pm.get_value(ic4.PropId.WIDTH)
                current_h_cam = self.pm.get_value(ic4.PropId.HEIGHT)

                if w > 0 and h > 0 and (w != current_w_cam or h != current_h_cam):
                    log.warning(
                        f"ROI size change (req: {w}x{h}, curr: {current_w_cam}x{current_h_cam}) requires camera restart. Not applying on-the-fly."
                    )
                elif w == 0 and h == 0:  # Special case to reset offset
                    self.pm.set_value(ic4.PropId.OFFSET_X, 0)
                    self.pm.set_value(ic4.PropId.OFFSET_Y, 0)
                    log.info(f"Reset OFFSET_X and OFFSET_Y to 0.")
                else:  # Apply offsets if size matches or if w/h in ROI are not meant to change size
                    self.pm.set_value(ic4.PropId.OFFSET_X, x)
                    self.pm.set_value(ic4.PropId.OFFSET_Y, y)
                    log.info(f"Set OFFSET_X={x}, OFFSET_Y={y}")

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
        prop_map = {
            "exposure": (ic4.PropId.EXPOSURE, ic4.PropId.EXPOSURE_AUTO),
            "gain": (ic4.PropId.GAIN, None),
        }

        for name, (val_pid, auto_pid) in prop_map.items():
            try:
                prop_val = self.pm.find(val_pid)
                p_info = {"enabled": prop_val.is_available and prop_val.is_writable}
                if p_info["enabled"]:
                    if isinstance(prop_val, (PropInteger, PropFloat)):
                        p_info["min"] = prop_val.minimum
                        p_info["max"] = prop_val.maximum
                        p_info["value"] = prop_val.value
                    elif isinstance(prop_val, PropEnumeration):
                        p_info["options"] = prop_val.options
                        p_info["value"] = prop_val.value

                    if auto_pid:
                        prop_auto = self.pm.find(auto_pid)
                        if prop_auto.is_available:
                            p_info["is_auto_on"] = bool(prop_auto.value)
                            p_info["auto_available"] = True
                        else:
                            p_info["auto_available"] = False
                props_dict["controls"][name] = p_info
            except (ic4.IC4Exception, AttributeError) as e:
                log.debug(f"Could not get property {name}: {e}")
                props_dict["controls"][name] = {"enabled": False}

        roi_props_dict = {}
        try:
            width_prop = self.pm.find(ic4.PropId.WIDTH)
            height_prop = self.pm.find(ic4.PropId.HEIGHT)
            offset_x_prop = self.pm.find(ic4.PropId.OFFSET_X)
            offset_y_prop = self.pm.find(ic4.PropId.OFFSET_Y)

            roi_props_dict["w"] = width_prop.value
            roi_props_dict["max_w"] = width_prop.maximum
            roi_props_dict["h"] = height_prop.value
            roi_props_dict["max_h"] = height_prop.maximum
            roi_props_dict["x"] = offset_x_prop.value
            roi_props_dict["max_x"] = offset_x_prop.maximum
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
            w = self.pm.get_value(ic4.PropId.WIDTH)
            h = self.pm.get_value(ic4.PropId.HEIGHT)
            pf_prop = self.pm.find(ic4.PropId.PIXEL_FORMAT)  # This is a property object
            pf_val_str = pf_prop.value  # Get current string value, e.g. "Mono 8"

            resolutions.append(f"{w}x{h} ({pf_val_str})")
            # To list all available formats, one would iterate pf_prop.options if it's PropEnumeration
            # For now, we only list the current active one. UI can offer standards.
        except ic4.IC4Exception as e:
            log.warning(f"Could not get current resolution details: {e}")

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
                current_pf_val = self.pm.get_value(ic4.PropId.PIXEL_FORMAT)
                log.info(f"Current camera pixel format: {current_pf_val}")
                desired_format_to_set = (
                    self.desired_pixel_format_str
                )  # Default to Mono 8

                # Try to set user's desired format, or "Mono 8" as a safe default for QImage
                # The DMK33UX250 is monochrome. "Mono 8" is usually available.
                if (
                    self.desired_pixel_format_str
                    and current_pf_val != self.desired_pixel_format_str
                ):
                    pf_prop_obj = self.pm.find(ic4.PropId.PIXEL_FORMAT)
                    if isinstance(pf_prop_obj, PropEnumeration):
                        available_formats = pf_prop_obj.options
                        log.info(
                            f"Available pixel formats on camera: {available_formats}"
                        )
                        if self.desired_pixel_format_str in available_formats:
                            desired_format_to_set = self.desired_pixel_format_str
                        elif (
                            "Mono 8" in available_formats
                        ):  # Fallback to Mono 8 if user's choice not there
                            desired_format_to_set = "Mono 8"
                            log.warning(
                                f"Desired format {self.desired_pixel_format_str} not found, falling back to 'Mono 8'"
                            )
                        else:  # Neither desired nor Mono 8 available from list, use current
                            desired_format_to_set = current_pf_val
                            log.warning(
                                f"Neither desired format '{self.desired_pixel_format_str}' nor 'Mono 8' found in options. Using camera current: {current_pf_val}"
                            )
                    else:  # Not an enum, just try to set what was desired.
                        desired_format_to_set = self.desired_pixel_format_str

                elif (
                    current_pf_val != "Mono 8"
                ):  # If no user preference, but not Mono 8, try to set Mono 8
                    pf_prop_obj = self.pm.find(ic4.PropId.PIXEL_FORMAT)
                    if (
                        isinstance(pf_prop_obj, PropEnumeration)
                        and "Mono 8" in pf_prop_obj.options
                    ):
                        desired_format_to_set = "Mono 8"
                    elif not isinstance(
                        pf_prop_obj, PropEnumeration
                    ):  # If not enum, can try setting
                        desired_format_to_set = "Mono 8"
                    else:  # Is enum, but "Mono 8" not in options. Keep current.
                        desired_format_to_set = current_pf_val

                if desired_format_to_set != current_pf_val:
                    self.pm.set_value(ic4.PropId.PIXEL_FORMAT, desired_format_to_set)
                    log.info(f"Set PIXEL_FORMAT to {desired_format_to_set}")

                self.current_pixel_format_name = self.pm.get_value(
                    ic4.PropId.PIXEL_FORMAT
                )
                if self.current_pixel_format_name == "Mono 8":
                    self.actual_qimage_format = QImage.Format_Grayscale8
                else:
                    log.error(
                        f"Camera pixel format is {self.current_pixel_format_name}, not 'Mono 8'. Live view might fail."
                    )
                    self.camera_error.emit(
                        f"Unsupported format: {self.current_pixel_format_name}. Requires 'Mono 8'.",
                        "PixelFormatError",
                    )
                    return

            except ic4.IC4Exception as e:
                log.error(f"Error setting/getting PIXEL_FORMAT: {e}")
                self.camera_error.emit(f"Pixel Format Error: {e}", type(e).__name__)
                return

            try:
                if self.desired_width is not None:
                    self.pm.set_value(ic4.PropId.WIDTH, self.desired_width)
                if self.desired_height is not None:
                    self.pm.set_value(ic4.PropId.HEIGHT, self.desired_height)
                self.current_frame_width = self.pm.get_value(ic4.PropId.WIDTH)
                self.current_frame_height = self.pm.get_value(ic4.PropId.HEIGHT)
                log.info(
                    f"Actual camera resolution: {self.current_frame_width}x{self.current_frame_height}"
                )
            except ic4.IC4Exception as e:
                log.warning(
                    f"Could not set/get WIDTH/HEIGHT: {e}. Using camera defaults."
                )
                self.current_frame_width = self.pm.get_value(ic4.PropId.WIDTH)
                self.current_frame_height = self.pm.get_value(ic4.PropId.HEIGHT)

            try:
                if self.pm.is_property_available(ic4.PropId.ACQUISITION_FRAME_RATE):
                    self.pm.set_value(
                        ic4.PropId.ACQUISITION_FRAME_RATE, float(self.target_fps)
                    )
                    log.info(
                        f"Set ACQUISITION_FRAME_RATE to {self.target_fps}, actual: {self.pm.get_value(ic4.PropId.ACQUISITION_FRAME_RATE)}"
                    )
            except ic4.IC4Exception as e:
                log.warning(f"Could not set frame rate: {e}")

            self._apply_pending_properties()
            self._emit_available_resolutions()
            self._emit_camera_properties()

            # Use QueueSink for continuous capture
            self.sink = ic4.QueueSink.create(accept_incomplete_frames=False)
            log.info(
                f"QueueSink created. Target format for sink: {self.current_pixel_format_name}"
            )

            # It's good practice to set the sink's output format if known,
            # though it often tries to match camera or convert.
            # For "Mono 8" from camera, sink output should also be "Mono 8" or compatible.
            # sink_pixel_format = ic4.PixelFormat.parse(self.current_pixel_format_name) # Requires PixelFormat to be Enum-like
            # self.sink.set_pixel_format(sink_pixel_format) # If such a method exists on QueueSink

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
                    # Pop buffer from QueueSink
                    buf = self.sink.pop(timeout_ms=100)  # timeout_ms is argument name
                except ic4.IC4Exception as e:
                    if e.code == ic4.ErrorCode.TIMEOUT:
                        continue
                    else:
                        log.error(f"IC4Exception during sink.pop: {e} (Code: {e.code})")
                        self.camera_error.emit(
                            str(e), f"IC4ExceptionSinkPop ({e.code})"
                        )
                        break

                if (
                    buf is None
                ):  # Should be caught by timeout exception, but as a safeguard
                    continue

                # is_incomplete might not be on buffer from QueueSink.pop directly, often handled by create()
                # if buf.is_incomplete: # Check documentation for QueueSink buffer properties
                #     log.warning("Received incomplete frame, discarding.")
                #     # buf.unlock() # QueueSink buffers might not need explicit unlock, check docs
                #     continue

                try:
                    frame_width = buf.image_type.width
                    frame_height = buf.image_type.height
                    # pixel_format_name = buf.image_type.pixel_format.name # String like "Mono 8"
                    stride = buf.image_type.stride_bytes

                    # Assuming actual_qimage_format was correctly set to Format_Grayscale8
                    if self.actual_qimage_format == QImage.Format_Invalid:
                        log.error(
                            f"Buffer received but QImage format is invalid. Current camera format: {self.current_pixel_format_name}"
                        )
                        # buf.unlock() # If needed
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
                    pass  # Buffers from QueueSink.pop are often managed by the sink/pool, explicit unlock might not be needed
                    # or could be harmful. Consult TIS examples for QueueSink.

                now = time.monotonic()
                dt = now - last_frame_time
                target_interval = (
                    1.0 / self.target_fps if self.target_fps > 0 else 0.05
                )  # Avoid div by zero
                if dt < target_interval:
                    sleep_duration_ms = int((target_interval - dt) * 1000)
                    if sleep_duration_ms > 5:  # Only sleep if significant
                        self.msleep(sleep_duration_ms)
                last_frame_time = time.monotonic()

        except RuntimeError as e:
            log.error(f"RuntimeError in camera thread: {e}")
            self.camera_error.emit(str(e), type(e).__name__)
        except ic4.IC4Exception as e:
            log.error(f"IC4Exception in camera thread: {e} (Code: {e.code})")
            self.camera_error.emit(str(e), f"IC4Exception ({e.code})")
        except Exception as e:
            log.exception("Unhandled exception in camera thread:")
            self.camera_error.emit(str(e), type(e).__name__)
        finally:
            log.info("Camera thread run() method finishing...")
            if self.grabber:
                if self.grabber.is_streaming():
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
