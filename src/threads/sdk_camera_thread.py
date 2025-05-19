import logging
import imagingcontrol4 as ic4
import time
from PyQt5.QtCore import QThread, pyqtSignal, QMutex, QWaitCondition
from PyQt5.QtGui import QImage
from imagingcontrol4 import (
    BufferSink,
    StreamSetupOption,
    ErrorCode,
    IC4Exception,
    PropId,
    PixelFormat,
)
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
    Uses BufferSink for continuous streaming and frames with wait_for_buffer.
    """

    frame_ready = pyqtSignal(QImage, object)  # Emits QImage and raw buffer array
    # Emits list of strings like "WidthxHeight (PixelFormat)"
    camera_resolutions_available = pyqtSignal(list)
    camera_properties_updated = pyqtSignal(dict)  # Emits dict of property states
    camera_error = pyqtSignal(str, str)  # Emits error message and error type name

    def __init__(
        self,
        device_info: ic4.DeviceInfo = None,  # Pass the specific device info
        target_fps: float = 20.0,
        desired_width: int = None,  # Allow None to use camera default initially
        desired_height: int = None,
        desired_pixel_format: str = "Mono 8",  # Target this format
        parent=None,
    ):
        super().__init__(parent)
        self._stop_requested = False
        self.device_info = device_info
        self.target_fps = target_fps
        self.desired_width = desired_width
        self.desired_height = desired_height
        self.desired_pixel_format_str = desired_pixel_format  # e.g., "Mono 8"

        self._pending_exposure_us = None
        self._pending_gain_db = None
        self._pending_auto_exposure = None
        self._pending_roi = None  # (x, y, w, h)

        self.grabber = None
        self.sink = None
        self.pm = None  # PropertyMap

        self.current_frame_width = 0
        self.current_frame_height = 0
        self.current_pixel_format_name = ""
        self.current_stride = 0
        self.actual_qimage_format = QImage.Format_Invalid

    def request_stop(self):
        """Signal the thread to stop; caller should wait() after."""
        log.debug("Stop requested for SDKCameraThread")
        self._stop_requested = True

    def update_exposure(self, exp_us: int):
        log.debug(f"SDKCameraThread: Queuing exposure update: {exp_us} us")
        self._pending_exposure_us = exp_us

    def update_gain(self, gain_db: float):  # TIS gain is often float (dB)
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

        # Order might matter: Auto exposure off before setting manual exposure
        if self._pending_auto_exposure is not None:
            try:
                current_auto = self.pm.get_value(PropId.EXPOSURE_AUTO)
                if current_auto != self._pending_auto_exposure:
                    self.pm.set_value(PropId.EXPOSURE_AUTO, self._pending_auto_exposure)
                    log.info(f"Set EXPOSURE_AUTO to {self._pending_auto_exposure}")
                    # Re-fetch exposure limits if auto exposure was turned off
                    if not self._pending_auto_exposure:
                        self._emit_camera_properties()  # Update UI with new ranges
            except IC4Exception as e:
                log.warning(f"Failed to set EXPOSURE_AUTO: {e}")
            except Exception as e:
                log.warning(f"Generic error setting EXPOSURE_AUTO: {e}")
            self._pending_auto_exposure = None

        if self._pending_exposure_us is not None:
            try:
                # Ensure auto exposure is off if we are setting manual exposure
                is_auto_on = self.pm.get_value(PropId.EXPOSURE_AUTO)
                if not is_auto_on:
                    self.pm.set_value(PropId.EXPOSURE, self._pending_exposure_us)
                    log.info(f"Set EXPOSURE to {self._pending_exposure_us} us")
                else:
                    log.info("Auto exposure is ON, not setting manual exposure.")
            except IC4Exception as e:
                log.warning(f"Failed to set EXPOSURE: {e}")
            except Exception as e:
                log.warning(f"Generic error setting EXPOSURE: {e}")
            self._pending_exposure_us = None

        if self._pending_gain_db is not None:
            try:
                self.pm.set_value(PropId.GAIN, self._pending_gain_db)
                log.info(f"Set GAIN to {self._pending_gain_db} dB")
            except IC4Exception as e:
                log.warning(f"Failed to set GAIN: {e}")
            except Exception as e:
                log.warning(f"Generic error setting GAIN: {e}")
            self._pending_gain_db = None

        # ROI needs stream stop/restart if changing size, not just offset
        # For simplicity here, assume it might need restart if not just offset.
        # A more advanced implementation would check if only offset X/Y changed.
        if self._pending_roi is not None:
            x, y, w, h = self._pending_roi
            requires_restart = False
            try:
                if w > 0 and h > 0:  # Only apply if width and height are valid
                    current_w = self.pm.get_value(PropId.WIDTH)
                    current_h = self.pm.get_value(PropId.HEIGHT)
                    if current_w != w or current_h != h:
                        requires_restart = True  # Size change needs restart

                    if requires_restart:
                        log.info(
                            "ROI size change detected, will require stream restart (not implemented on-the-fly here). For now, set and hope."
                        )
                        # Ideally: self.grabber.stream_stop()
                        # self.pm.set_value(PropId.WIDTH, w)
                        # self.pm.set_value(PropId.HEIGHT, h)
                        # self.pm.set_value(PropId.OFFSET_X, x)
                        # self.pm.set_value(PropId.OFFSET_Y, y)
                        # self.grabber.stream_setup(...) and self.grabber.stream_start()
                        # This basic version will just try to set offset if size is same.
                        # Full ROI change usually requires re-doing stream_setup.
                        log.warning(
                            "Dynamic ROI size change not fully supported without stream restart. Applying offsets only if size matches."
                        )
                        if not requires_restart:
                            self.pm.set_value(PropId.OFFSET_X, x)
                            self.pm.set_value(PropId.OFFSET_Y, y)
                            log.info(f"Set OFFSET_X={x}, OFFSET_Y={y}")
                        else:  # If size needs to change, it should be handled by re-creating the thread with new width/height
                            log.info(
                                f"ROI change requested: x={x}, y={y}, w={w}, h={h}. Current w={current_w}, h={current_h}"
                            )
                            log.warning(
                                "ROI size change requires camera restart. This change might not apply or might error."
                            )

                else:  # Reset ROI offsets if w or h is zero (or invalid)
                    self.pm.set_value(
                        PropId.OFFSET_X, 0
                    )  # Assuming 0 is the default/min
                    self.pm.set_value(PropId.OFFSET_Y, 0)
                    log.info("Reset OFFSET_X and OFFSET_Y due to invalid ROI w/h")

            except IC4Exception as e:
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
            "exposure": (PropId.EXPOSURE, PropId.EXPOSURE_AUTO),
            "gain": (PropId.GAIN, None),
            # "brightness" is not a standard TIS GenICam property, usually controlled via gamma or gain.
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
                        p_info["options"] = prop_val.options  # list of strings
                        p_info["value"] = prop_val.value  # current selected string

                    if auto_pid:
                        prop_auto = self.pm.find(auto_pid)
                        if prop_auto.is_available:
                            p_info["is_auto_on"] = bool(
                                prop_auto.value
                            )  # Ensure it's Python bool
                            p_info["auto_available"] = True
                            # If auto is on, value slider might be disabled by UI
                        else:
                            p_info["auto_available"] = False
                props_dict["controls"][name] = p_info
            except (IC4Exception, AttributeError) as e:
                log.debug(f"Could not get property {name}: {e}")
                props_dict["controls"][name] = {"enabled": False}

        # ROI Properties
        roi_props_dict = {}
        try:
            width_prop = self.pm.find(PropId.WIDTH)
            height_prop = self.pm.find(PropId.HEIGHT)
            offset_x_prop = self.pm.find(PropId.OFFSET_X)
            offset_y_prop = self.pm.find(PropId.OFFSET_Y)

            roi_props_dict["w"] = width_prop.value
            roi_props_dict["max_w"] = (
                width_prop.maximum
            )  # Max possible width (sensor width)
            roi_props_dict["h"] = height_prop.value
            roi_props_dict["max_h"] = height_prop.maximum  # Max possible height
            roi_props_dict["x"] = offset_x_prop.value
            roi_props_dict["max_x"] = offset_x_prop.maximum  # Max offset X
            roi_props_dict["y"] = offset_y_prop.value
            roi_props_dict["max_y"] = offset_y_prop.maximum

            props_dict["roi"] = roi_props_dict
        except (IC4Exception, AttributeError) as e:
            log.debug(f"Could not get ROI properties: {e}")
            props_dict["roi"] = {"max_w": 0, "max_h": 0}  # Indicate ROI not available

        log.debug(f"Emitting camera_properties_updated: {props_dict}")
        self.camera_properties_updated.emit(props_dict)

    def _emit_available_resolutions(self):
        # For TIS cameras, resolutions are often defined by Width, Height, and PixelFormat combinations.
        # A simple approach: provide current and some standard ones if the camera supports them.
        # A more robust way is to query Enum Properties for Width/Height if they exist,
        # or provide a few common resolutions that can be attempted.
        # For now, just emit the current resolution.
        if not self.pm:
            self.camera_resolutions_available.emit([])
            return

        resolutions = []
        try:
            w = self.pm.get_value(PropId.WIDTH)
            h = self.pm.get_value(PropId.HEIGHT)
            pf_prop = self.pm.find(PropId.PIXEL_FORMAT)
            pf_val_str = pf_prop.value  # This is usually the string like "Mono 8"

            resolutions.append(f"{w}x{h} ({pf_val_str})")
            # Potentially add other common resolutions if we know how to check/set them.
            # Example: if camera supports enumeration for width/height.
            # For this version, we'll keep it simple and mainly rely on user input for desired W/H
            # or the camera's default. The qtcamera_widget can offer some standard sizes.
        except IC4Exception as e:
            log.warning(f"Could not get current resolution details: {e}")

        log.debug(f"Emitting camera_resolutions_available: {resolutions}")
        self.camera_resolutions_available.emit(resolutions)

    def run(self):
        log.info(
            f"SDKCameraThread started for device: {self.device_info.model_name if self.device_info else 'Unknown (No DeviceInfo)'}, "
            f"Desired WxH: {self.desired_width}x{self.desired_height}, Format: {self.desired_pixel_format_str}, FPS: {self.target_fps}"
        )
        self.grabber = ic4.Grabber()

        try:
            if not self.device_info:
                devices = ic4.DeviceEnum.devices()
                if not devices:
                    raise RuntimeError("No TIS cameras found.")
                self.device_info = devices[
                    0
                ]  # Default to first camera if none specified
                log.info(
                    f"No device_info provided, selected first available: {self.device_info.model_name} (S/N {self.device_info.serial})"
                )

            self.grabber.device_open(self.device_info)
            log.info(f"Device opened: {self.device_info.model_name}")
            self.pm = self.grabber.device_property_map

            # --- Configure Camera ---
            # 1. Pixel Format (Attempt to set desired, then read back)
            try:
                current_pf_val = self.pm.get_value(PropId.PIXEL_FORMAT)  # String value
                log.info(f"Current camera pixel format: {current_pf_val}")
                if (
                    self.desired_pixel_format_str
                    and current_pf_val != self.desired_pixel_format_str
                ):
                    # Check if desired format is available
                    pf_prop = self.pm.find(PropId.PIXEL_FORMAT)
                    if isinstance(pf_prop, PropEnumeration):
                        available_formats = pf_prop.options
                        log.info(f"Available pixel formats: {available_formats}")
                        if self.desired_pixel_format_str in available_formats:
                            self.pm.set_value(
                                PropId.PIXEL_FORMAT, self.desired_pixel_format_str
                            )
                            log.info(
                                f"Set PIXEL_FORMAT to {self.desired_pixel_format_str}"
                            )
                        else:
                            log.warning(
                                f"Desired pixel format {self.desired_pixel_format_str} not in available options. Using camera current: {current_pf_val}"
                            )
                            self.desired_pixel_format_str = current_pf_val  # Fallback
                    else:  # Not an enum, try setting directly
                        self.pm.set_value(
                            PropId.PIXEL_FORMAT, self.desired_pixel_format_str
                        )
                        log.info(
                            f"Set PIXEL_FORMAT to {self.desired_pixel_format_str} (non-enum)"
                        )
                else:
                    log.info(
                        f"Camera already in desired pixel format or no desired format specified. Using: {current_pf_val}"
                    )
                    self.desired_pixel_format_str = current_pf_val

                # Update internal state with actual format
                self.current_pixel_format_name = self.pm.get_value(PropId.PIXEL_FORMAT)
                if (
                    self.current_pixel_format_name == "Mono 8"
                ):  # TIS specific string for 8-bit mono
                    self.actual_qimage_format = QImage.Format_Grayscale8
                elif (
                    self.current_pixel_format_name == "Mono 10"
                    or self.current_pixel_format_name == "Mono 12"
                    or self.current_pixel_format_name == "Mono 16"
                ):
                    # QImage doesn't directly support these. We'd need conversion.
                    # For simplicity, we'll emit an error or try to force Mono 8.
                    # Here, we rely on having set it to "Mono 8". If it's still >8bit, QImage will be invalid.
                    log.warning(
                        f"Pixel format is {self.current_pixel_format_name}. QImage might not display correctly without conversion to 8-bit."
                    )
                    # Attempt to force Mono 8 again if primary attempt failed
                    if self.current_pixel_format_name != "Mono 8":
                        try:
                            log.info(
                                "Attempting to force PIXEL_FORMAT to 'Mono 8' as fallback."
                            )
                            self.pm.set_value(PropId.PIXEL_FORMAT, "Mono 8")
                            self.current_pixel_format_name = self.pm.get_value(
                                PropId.PIXEL_FORMAT
                            )
                            if self.current_pixel_format_name == "Mono 8":
                                self.actual_qimage_format = QImage.Format_Grayscale8
                                log.info("Successfully forced PIXEL_FORMAT to 'Mono 8'")
                            else:
                                raise RuntimeError(
                                    f"Failed to force 'Mono 8', current is {self.current_pixel_format_name}"
                                )
                        except Exception as force_e:
                            self.camera_error.emit(
                                f"Unsupported pixel format: {self.current_pixel_format_name}. Needs Mono 8. Error forcing: {force_e}",
                                "PixelFormatError",
                            )
                            return  # Critical error, cannot proceed
                # Add more mappings if needed (e.g., for color formats)
                else:
                    self.camera_error.emit(
                        f"Unsupported pixel format from camera: {self.current_pixel_format_name}",
                        "PixelFormatError",
                    )
                    return  # Critical error

            except IC4Exception as e:
                log.error(f"Error setting/getting PIXEL_FORMAT: {e}")
                self.camera_error.emit(f"Pixel Format Error: {e}", type(e).__name__)
                return
            except Exception as e:
                log.error(f"Generic error with PIXEL_FORMAT: {e}")
                self.camera_error.emit(
                    f"Pixel Format Setup Error: {e}", type(e).__name__
                )
                return

            # 2. Width & Height (Attempt to set if specified, then read back)
            try:
                if self.desired_width is not None:
                    self.pm.set_value(PropId.WIDTH, self.desired_width)
                    log.info(f"Set WIDTH to {self.desired_width}")
                if self.desired_height is not None:
                    self.pm.set_value(PropId.HEIGHT, self.desired_height)
                    log.info(f"Set HEIGHT to {self.desired_height}")

                self.current_frame_width = self.pm.get_value(PropId.WIDTH)
                self.current_frame_height = self.pm.get_value(PropId.HEIGHT)
                log.info(
                    f"Actual camera resolution: {self.current_frame_width}x{self.current_frame_height}"
                )

            except IC4Exception as e:
                log.warning(
                    f"Could not set/get WIDTH/HEIGHT: {e}. Using camera defaults."
                )
                self.current_frame_width = self.pm.get_value(
                    PropId.WIDTH
                )  # Read whatever it is
                self.current_frame_height = self.pm.get_value(PropId.HEIGHT)
                log.info(
                    f"Using camera current resolution: {self.current_frame_width}x{self.current_frame_height}"
                )

            # 3. Frame Rate (TIS uses AcquisitionFrameRate property)
            try:
                if self.pm.is_property_available(PropId.ACQUISITION_FRAME_RATE):
                    self.pm.set_value(
                        PropId.ACQUISITION_FRAME_RATE, float(self.target_fps)
                    )
                    actual_fps = self.pm.get_value(PropId.ACQUISITION_FRAME_RATE)
                    log.info(
                        f"Set ACQUISITION_FRAME_RATE to {self.target_fps}, actual: {actual_fps}"
                    )
                elif self.pm.is_property_available(
                    PropId.FRAMERATE
                ):  # Some older cameras might use this
                    self.pm.set_value(PropId.FRAMERATE, float(self.target_fps))
                    actual_fps = self.pm.get_value(PropId.FRAMERATE)
                    log.info(
                        f"Set FRAMERATE to {self.target_fps}, actual: {actual_fps}"
                    )
                else:
                    log.info(
                        "No direct frame rate property found/set, relying on acquisition loop timing."
                    )
            except IC4Exception as e:
                log.warning(f"Could not set frame rate: {e}")
            except Exception as e:
                log.warning(f"Generic error setting frame rate: {e}")

            # Apply initial pending properties (e.g. exposure, gain passed in constructor indirectly)
            self._apply_pending_properties()  # Initial application of any default/pending

            # Emit initial camera capabilities
            self._emit_available_resolutions()
            self._emit_camera_properties()

            # --- Setup Stream ---
            self.sink = BufferSink()
            self.sink.set_accept_incomplete_frames(
                False
            )  # Or True if you want to handle them

            # Define the data stream format based on actual camera settings
            # The sink will try to match this or convert if possible.
            # For simplicity, let sink derive from camera. More complex: specify sink format.

            self.grabber.stream_setup(
                self.sink, setup_option=StreamSetupOption.ACQUISITION_START
            )
            log.info(
                f"Stream setup done. Sink format: {self.sink.common_pixel_format.name if self.sink.common_pixel_format else 'N/A'}"
            )

            # Get stride AFTER stream setup, as it might depend on sink configuration
            # For TIS, buffer_parts[0].stride_bytes or image_type.stride_bytes
            # This part is tricky, let's assume the frame buffer object later will provide stride.

            log.info("Starting stream...")
            self.grabber.stream_start()
            log.info("Streaming started.")

            last_frame_time = time.monotonic()
            frame_count = 0

            while not self._stop_requested:
                self._apply_pending_properties()  # Apply any GUI changes

                try:
                    # Timeout is important to allow checking _stop_requested and applying properties
                    buf = self.sink.wait_for_buffer(
                        timeout_ms=100
                    )  # Shorter timeout for responsiveness
                except IC4Exception as e:
                    if e.code == ErrorCode.TIMEOUT:
                        # log.debug("Buffer timeout, continuing.")
                        continue
                    else:
                        log.error(
                            f"IC4Exception during wait_for_buffer: {e} (Code: {e.code})"
                        )
                        self.camera_error.emit(str(e), f"IC4Exception ({e.code.name})")
                        break  # Exit loop on other critical sink errors

                if (
                    buf is None
                ):  # Should be caught by timeout exception, but as a safeguard
                    continue

                if buf.is_incomplete:
                    log.warning("Received incomplete frame, discarding.")
                    buf.unlock()  # Release buffer back to SDK
                    continue

                try:
                    # Accessing buffer data and properties:
                    # `buf.mem_ptr`, `buf.mem_size`
                    # `buf.image_type.width`, `buf.image_type.height`
                    # `buf.image_type.pixel_format.name` (e.g. "Mono 8")
                    # `buf.image_type.stride_bytes`

                    frame_width = buf.image_type.width
                    frame_height = buf.image_type.height
                    pixel_format_name = (
                        buf.image_type.pixel_format.name
                    )  # String like "Mono 8"
                    stride = buf.image_type.stride_bytes

                    # log.debug(f"Frame: {frame_width}x{frame_height}, Stride: {stride}, Format: {pixel_format_name}")

                    qimage_format_for_buffer = QImage.Format_Invalid
                    if pixel_format_name == "Mono 8":
                        qimage_format_for_buffer = QImage.Format_Grayscale8
                    # Add elif for other formats if you support them (e.g. RGB8 -> Format_RGB888)
                    # elif pixel_format_name == "RGB8": # Example for a color format
                    #    qimage_format_for_buffer = QImage.Format_RGB888

                    if qimage_format_for_buffer == QImage.Format_Invalid:
                        log.error(
                            f"Buffer received with unsupported pixel format: {pixel_format_name}. Cannot create QImage."
                        )
                        # self.camera_error.emit(f"Unsupported live format: {pixel_format_name}", "PixelFormatError")
                        # Potentially stop the thread or try to reconfigure. For now, just log and skip.
                        buf.unlock()
                        continue

                    # Create QImage directly from the buffer's memory
                    # QImage constructor taking const uchar* data
                    qimg = QImage(
                        buf.mem_ptr,
                        frame_width,
                        frame_height,
                        stride,
                        qimage_format_for_buffer,
                    )

                    if qimg.isNull():
                        log.warning(
                            "Created QImage is null. Check format, width, height, stride."
                        )
                    else:
                        # Must copy() the QImage if it's going to another thread (GUI)
                        # or if the underlying buffer will be released before Qt processes it.
                        # Since buf.unlock() is called, a copy is essential.
                        self.frame_ready.emit(
                            qimg.copy(), buf.mem_ptr
                        )  # Pass raw buffer as object if needed

                    frame_count += 1
                finally:
                    buf.unlock()  # IMPORTANT: Release the buffer back to the SDK

                # FPS control / yielding
                now = time.monotonic()
                dt = now - last_frame_time
                target_interval = 1.0 / self.target_fps
                if dt < target_interval:
                    sleep_duration_ms = int((target_interval - dt) * 1000)
                    if sleep_duration_ms > 0:
                        self.msleep(sleep_duration_ms)
                last_frame_time = time.monotonic()  # Reset for next frame interval

        except RuntimeError as e:  # Catch "No TIS cameras found" etc.
            log.error(f"RuntimeError in camera thread: {e}")
            self.camera_error.emit(str(e), type(e).__name__)
        except IC4Exception as e:
            log.error(
                f"IC4Exception in camera thread: {e} (Code: {e.code.name if hasattr(e.code, 'name') else e.code})"
            )
            self.camera_error.emit(
                str(e),
                f"IC4Exception ({e.code.name if hasattr(e.code, 'name') else e.code})",
            )
        except Exception as e:
            log.exception(
                "Unhandled exception in camera thread:"
            )  # Will print stack trace
            self.camera_error.emit(str(e), type(e).__name__)
        finally:
            log.info("Camera thread run() method finishing...")
            if self.grabber:
                if self.grabber.is_streaming():
                    try:
                        log.info("Stopping stream...")
                        self.grabber.stream_stop()
                    except IC4Exception as e:
                        log.error(f"Error stopping stream: {e}")
                if self.grabber.is_device_open:
                    try:
                        log.info("Closing device...")
                        self.grabber.device_close()
                    except IC4Exception as e:
                        log.error(f"Error closing device: {e}")
            self.grabber = None  # Release grabber
            self.sink = None
            self.pm = None
            log.info(
                f"SDKCameraThread ({self.device_info.model_name if self.device_info else 'N/A'}) stopped."
            )
