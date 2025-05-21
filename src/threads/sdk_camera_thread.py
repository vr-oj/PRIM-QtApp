import logging
import time
import ctypes
import imagingcontrol4 as ic4

from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QImage

from imagingcontrol4.properties import (
    PropInteger,
    PropFloat,
    PropEnumeration,
)

log = logging.getLogger(__name__)

# camera-property names
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
            f"DummyListener: Sink connected. {image_type}, MinBuffers={min_buffers_required}"
        )
        return True

    def frames_queued(self, sink):
        pass

    def sink_disconnected(self, sink):
        log.debug(f"DummyListener: Sink disconnected ({type(sink)})")


class SDKCameraThread(QThread):
    # emitted whenever a new frame is ready: (QImage copy, raw_buffer)
    frame_ready = pyqtSignal(QImage, object)

    # emitted once after opening, with a list of resolution strings
    camera_resolutions_available = pyqtSignal(list)
    camera_video_formats_available = pyqtSignal(list)

    # emitted whenever exposure/gain/ROI props change, to repopulate your UI
    camera_properties_updated = pyqtSignal(dict)

    # emitted on any camera error: (message, code)
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

        # user-requested parameters (we keep them for signature compatibility)
        self.device_info = device_info
        self.target_fps = target_fps
        self.desired_width = desired_width
        self.desired_height = desired_height
        self.desired_pixel_format_str = desired_pixel_format

        # internal flags & throttling
        self._stop_requested = False
        self._pending_exposure_us = None
        self._pending_gain_db = None
        self._pending_auto_exposure = None
        self._pending_roi = None

        # debounce apply interval
        self._prop_throttle_interval = 0.1
        self._last_prop_apply_time = 0.0

        # runtime objects
        self.grabber = None
        self.sink = None
        self.pm = None
        self.actual_qimage_format = QImage.Format_Invalid

        # listener for QueueSink
        self.dummy_listener = DummySinkListener()

        self.selected_video_format_identifier = None

    def request_stop(self):
        self._stop_requested = True

    # these are called from the GUI thread
    def update_exposure(self, exp_us: int):
        self._pending_exposure_us = float(exp_us)

    def update_gain(self, gain_db: float):
        self._pending_gain_db = gain_db

    def update_auto_exposure(self, auto: bool):
        self._pending_auto_exposure = auto

    def update_roi(self, x: int, y: int, w: int, h: int):
        self._pending_roi = (x, y, w, h)

    @pyqtSlot(str)
    def select_video_format(self, format_identifier: str):
        log.info(
            f"SDKCameraThread: Request to select video format ID: {format_identifier}"
        )
        self.selected_video_format_identifier = format_identifier

    def _is_prop_writable(self, prop):
        return bool(
            prop and prop.is_available and not getattr(prop, "is_readonly", True)
        )

    def _set_property_value(self, name: str, val):
        try:
            p = self.pm.find(name)
            if self._is_prop_writable(p):
                self.pm.set_value(name, val)
                log.info(f"Set {name} → {val}")
                return True
            elif p and p.is_available:
                log.warning(f"{name} is read-only")
        except Exception as e:
            log.warning(f"Failed to set {name}: {e}")
        return False

    def _apply_pending_properties(self):
        now = time.monotonic()
        if now - self._last_prop_apply_time < self._prop_throttle_interval:
            return
        self._last_prop_apply_time = now

        if not (self.pm and self.grabber and self.grabber.is_device_open):
            return

        # auto-exposure toggle
        if self._pending_auto_exposure is not None:
            pa = self.pm.find(PROP_EXPOSURE_AUTO)
            if pa and pa.is_available:
                val = "Continuous" if self._pending_auto_exposure else "Off"
                self._set_property_value(
                    PROP_EXPOSURE_AUTO,
                    (
                        val
                        if isinstance(pa, PropEnumeration)
                        else self._pending_auto_exposure
                    ),
                )
                if not self._pending_auto_exposure:
                    # force properties update immediately
                    self._emit_camera_properties()
            self._pending_auto_exposure = None

        # manual exposure
        if self._pending_exposure_us is not None:
            pa = self.pm.find(PROP_EXPOSURE_AUTO)
            auto_on = False
            if pa and pa.is_available:
                av = pa.value
                auto_on = (av != "Off") if isinstance(av, str) else bool(av)
            if not auto_on:
                self._set_property_value(PROP_EXPOSURE_TIME, self._pending_exposure_us)
            self._pending_exposure_us = None

        # gain
        if self._pending_gain_db is not None:
            self._set_property_value(PROP_GAIN, self._pending_gain_db)
            self._pending_gain_db = None

        # ROI offsets
        if self._pending_roi is not None:
            x, y, w, h = self._pending_roi
            if (w, h) == (0, 0):
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

        info = {"controls": {}, "roi": {}}

        # exposure & gain
        for key, (pv, pa) in {
            "exposure": (PROP_EXPOSURE_TIME, PROP_EXPOSURE_AUTO),
            "gain": (PROP_GAIN, None),
        }.items():
            ctrl = {"enabled": False, "value": 0, "min": 0, "max": 0}
            try:
                p = self.pm.find(pv)
                if p and p.is_available:
                    ctrl["enabled"] = self._is_prop_writable(p)
                    if isinstance(p, (PropInteger, PropFloat)):
                        ctrl.update(min=p.minimum, max=p.maximum, value=p.value)
                    elif isinstance(p, PropEnumeration):
                        ctrl.update(options=[e.name for e in p.entries], value=p.value)
                    if pa:
                        pap = self.pm.find(pa)
                        if pap and pap.is_available:
                            av = pap.value
                            is_auto = (av != "Off") if isinstance(av, str) else bool(av)
                            ctrl["auto_available"] = True
                            ctrl["is_auto_on"] = is_auto
                            if key == "exposure" and is_auto:
                                ctrl["enabled"] = False
            except Exception:
                pass
            info["controls"][key] = ctrl

        # ROI state
        try:
            roi = {}
            for label, pname in [
                ("w", PROP_WIDTH),
                ("h", PROP_HEIGHT),
                ("x", PROP_OFFSET_X),
                ("y", PROP_OFFSET_Y),
            ]:
                p = self.pm.find(pname)
                roi[label] = p.value
                if hasattr(p, "maximum"):
                    roi[f"max_{label}"] = p.maximum
            info["roi"] = roi
        except Exception:
            pass

        self.camera_properties_updated.emit(info)

    def _emit_current_settings_as_format_option(self):
        # Fallback if proper video format enumeration fails
        try:
            if not self.pm:
                log.warning("Property map not available for fallback format emission.")
                self.camera_video_formats_available.emit([])
                return

            w_prop = self.pm.find(PROP_WIDTH)
            h_prop = self.pm.find(PROP_HEIGHT)
            pf_prop = self.pm.find(PROP_PIXEL_FORMAT)

            if not (
                w_prop
                and w_prop.is_available
                and h_prop
                and h_prop.is_available
                and pf_prop
                and pf_prop.is_available
            ):
                log.warning(
                    "Width, Height, or PixelFormat properties not available for fallback."
                )
                self.camera_video_formats_available.emit([])
                return

            w = w_prop.value
            h = h_prop.value
            pf_val = pf_prop.value

            # Handle cases where pf_val might be an enum entry or a string
            if hasattr(pf_val, "name"):  # If it's an enum entry object
                pf_name = pf_val.name
            elif isinstance(pf_val, str):  # If it's already a string
                pf_name = pf_val
            else:  # Fallback if it's something unexpected (e.g. int id of pixel format)
                pf_name = str(pf_val)

            dummy_id = f"current_{w}x{h}_{pf_name.replace(' ','_')}"  # Make a somewhat unique ID
            display_text = f"{w}x{h} ({pf_name})"

            log.info(
                f"Emitting fallback video format option: {display_text} (ID: {dummy_id})"
            )
            self.camera_video_formats_available.emit(
                [{"text": display_text, "id": dummy_id}]
            )

            # Also set this as the 'selected' one if no other choice yet
            if not self.selected_video_format_identifier:
                self.selected_video_format_identifier = dummy_id
                log.info(
                    f"Set selected_video_format_identifier to fallback: {dummy_id}"
                )

        except Exception as e:
            log.error(
                f"Failed to emit current settings as format option: {e}", exc_info=True
            )
            self.camera_video_formats_available.emit([])

    #    def _emit_available_resolutions(self):
    #        if not self.pm:
    #            self.camera_resolutions_available.emit([])
    #            return
    #
    #        try:
    #            w = self.pm.find(PROP_WIDTH).value
    #            h = self.pm.find(PROP_HEIGHT).value
    #            pf = self.pm.find(PROP_PIXEL_FORMAT).value
    #            self.camera_resolutions_available.emit([f"{w}x{h} ({pf})"]) # This signal is still used by CameraControlPanel for now
    #        except Exception as e:
    #            log.warning(f"Couldn’t list resolutions: {e}")
    #            self.camera_resolutions_available.emit([])

    def run(self):
        log.info(
            f"SDKCameraThread starting for {self.device_info.model_name if self.device_info else 'Unknown'}"
        )
        self.grabber = ic4.Grabber()
        try:
            # pick first camera if none given
            if not self.device_info:
                devs = ic4.DeviceEnum.devices()
                if not devs:
                    raise RuntimeError("No cameras found")
                self.device_info = devs[0]

            self.grabber.device_open(self.device_info)
            self.pm = self.grabber.device_property_map
            log.info(f"Opened {self.device_info.model_name}")

            # === NEW CAMERA SETUP LOGIC START ===
            try:
                # STEP A: Enumerate and emit available video formats
                available_formats_for_ui = []
                try:
                    # Ensure device is open before accessing video_format_descs
                    if not self.grabber.is_device_open:
                        raise RuntimeError(
                            "Device is not open before enumerating video formats."
                        )

                    video_format_descs = self.device_info.get_video_format_descs()
                    if not video_format_descs:
                        log.warning(
                            "Camera did not report any video format descriptors. Using fallback."
                        )
                        self._emit_current_settings_as_format_option()
                    else:
                        log.info(f"Found {len(video_format_descs)} video formats.")
                        for i, desc in enumerate(video_format_descs):
                            display_text = (
                                f"{desc.width}x{desc.height} ({desc.pixel_format.name})"
                            )
                            # The identifier is crucial for setting the format later
                            available_formats_for_ui.append(
                                {"text": display_text, "id": desc.identifier_string}
                            )

                        if available_formats_for_ui:
                            # Default selection logic:
                            # If a format was pre-selected (e.g., by QtCameraWidget restarting us with a choice)
                            # and that ID is valid, use it. Otherwise, pick a sensible default.
                            current_selected_id_is_valid = False
                            if self.selected_video_format_identifier:
                                for fmt_info in available_formats_for_ui:
                                    if (
                                        fmt_info["id"]
                                        == self.selected_video_format_identifier
                                    ):
                                        current_selected_id_is_valid = True
                                        break

                            if (
                                not current_selected_id_is_valid
                            ):  # If no valid pre-selection, pick a default
                                # Try to find a "Mono 8" format, preferably smaller for default
                                default_fmt_id = None
                                for fmt_info in available_formats_for_ui:
                                    if (
                                        "Mono8" in fmt_info["text"]
                                        or "Mono 8" in fmt_info["text"]
                                    ):  # Case for "Mono8" or "Mono 8"
                                        if self.desired_width and self.desired_height:
                                            if (
                                                str(self.desired_width)
                                                in fmt_info["text"]
                                                and str(self.desired_height)
                                                in fmt_info["text"]
                                            ):
                                                default_fmt_id = fmt_info["id"]
                                                break
                                        elif (
                                            not default_fmt_id
                                        ):  # Fallback to first mono8 if specific size not found
                                            default_fmt_id = fmt_info["id"]

                                if default_fmt_id:
                                    self.selected_video_format_identifier = (
                                        default_fmt_id
                                    )
                                elif (
                                    available_formats_for_ui
                                ):  # Ultimate fallback to the very first format
                                    self.selected_video_format_identifier = (
                                        available_formats_for_ui[0]["id"]
                                    )
                                log.info(
                                    f"Default/Initial video format ID set to: {self.selected_video_format_identifier}"
                                )
                        else:  # Should be covered by the "not video_format_descs" case
                            self._emit_current_settings_as_format_option()

                    # Emit the full list for the UI to populate
                    self.camera_video_formats_available.emit(available_formats_for_ui)

                except Exception as e_vf_enum:
                    log.error(
                        f"Error enumerating video formats: {e_vf_enum}", exc_info=True
                    )
                    self.camera_error.emit(
                        f"VideoFormatEnum: {e_vf_enum}", type(e_vf_enum).__name__
                    )
                    self._emit_current_settings_as_format_option()  # Attempt fallback

                # STEP B: Apply the selected video format
                if not self.selected_video_format_identifier:
                    log.error(
                        "No video format identifier was selected or determined. Cannot proceed with camera setup."
                    )
                    self.camera_error.emit("NoVideoFormat", "RuntimeError")
                    return  # Critical failure

                try:
                    log.info(
                        f"Attempting to set video format using identifier: '{self.selected_video_format_identifier}'"
                    )
                    self.grabber.video_format = (
                        self.selected_video_format_identifier
                    )  # This is the 'set' operation

                    # After setting, retrieve the current video format object
                    current_video_format_object = self.grabber.video_format

                    if hasattr(current_video_format_object, "name") and hasattr(
                        current_video_format_object, "identifier_string"
                    ):
                        log.info(
                            f"Successfully set and retrieved video format. "
                            f"Current format name: '{current_video_format_object.name}', "
                            f"ID: '{current_video_format_object.identifier_string}'"
                        )
                        log.info(
                            f"Current Actual Settings: W={self.pm.find(PROP_WIDTH).value}, "
                            f"H={self.pm.find(PROP_HEIGHT).value}, "
                            f"PF='{self.pm.find(PROP_PIXEL_FORMAT).value}'"
                        )  # PF value might be an enum or string
                    else:
                        # This might happen if the set failed and 'current_video_format_object' is still a string or None
                        log.warning(
                            f"Video format may not have been set correctly. "
                            f"Retrieved grabber.video_format type: {type(current_video_format_object)}, value: {current_video_format_object}"
                        )
                        # Attempt to log basic properties directly if the format object isn't as expected
                        log.info(
                            f"Current Actual Settings (direct query): W={self.pm.find(PROP_WIDTH).value}, "
                            f"H={self.pm.find(PROP_HEIGHT).value}, "
                            f"PF='{self.pm.find(PROP_PIXEL_FORMAT).value}'"
                        )

                    # Determine QImage format based on the actual pixel format
                    # This logic needs to use the property map value, as video_format object might not directly give simple string
                    pf_property_value = self.pm.find(PROP_PIXEL_FORMAT).value
                    current_pf_name_from_prop = pf_property_value
                    if hasattr(
                        pf_property_value, "name"
                    ):  # If it's an enum entry object
                        current_pf_name_from_prop = pf_property_value.name
                    elif isinstance(pf_property_value, str):  # If it's already a string
                        current_pf_name_from_prop = pf_property_value
                    else:  # Fallback
                        current_pf_name_from_prop = str(pf_property_value)

                    current_pf_name_lower = current_pf_name_from_prop.lower()
                    log.info(
                        f"Determining QImage format based on PixelFormat property: '{current_pf_name_lower}'"
                    )

                    if "mono8" in current_pf_name_lower:
                        self.actual_qimage_format = QImage.Format_Grayscale8
                    # ... (rest of your pixel format mapping logic) ...

                    # Determine QImage format based on the actual pixel format set by the video format
                    current_pf_name = self.pm.find(PROP_PIXEL_FORMAT).value
                    if isinstance(
                        current_pf_name, ic4.PixelFormatInfo
                    ):  # if it's an object
                        current_pf_name = current_pf_name.name
                    current_pf_name = current_pf_name.lower()

                    if "mono8" in current_pf_name:
                        self.actual_qimage_format = QImage.Format_Grayscale8
                    elif any(
                        pf in current_pf_name for pf in ["mono10", "mono12", "mono16"]
                    ):
                        log.warning(
                            f"Pixel format {current_pf_name} will be displayed as Grayscale8. Data may be scaled/truncated if QImage.Format_Grayscale16 is not used or conversion is not implemented."
                        )
                        self.actual_qimage_format = (
                            QImage.Format_Grayscale8
                        )  # Consider QImage.Format_Grayscale16 if appropriate and handled downstream
                    # Add more pixel format mappings here if needed (e.g., BayerRG8 -> QImage.Format_RGB888 after debayering, etc.)
                    else:
                        log.warning(
                            f"Unhandled pixel format from camera for QImage: {current_pf_name}. Defaulting to Invalid."
                        )
                        self.actual_qimage_format = QImage.Format_Invalid

                except Exception as e_vf_set:
                    log.error(
                        f"Failed to set video format ID '{self.selected_video_format_identifier}': {e_vf_set}",
                        exc_info=True,
                    )
                    self.camera_error.emit(
                        f"VideoFormatSet: {e_vf_set}", type(e_vf_set).__name__
                    )
                    return  # Critical failure

                # STEP C: Configure FrameRate *after* video format is set
                fps_prop = self.pm.find(PROP_ACQUISITION_FRAME_RATE)
                desired_fps_to_set = float(self.target_fps)

                if fps_prop and fps_prop.is_available:
                    try:
                        min_fps = fps_prop.minimum
                        max_fps = fps_prop.maximum
                        log.info(
                            f"Property '{PROP_ACQUISITION_FRAME_RATE}' valid range for current format: {min_fps:.2f} - {max_fps:.2f} FPS"
                        )

                        if not (min_fps <= desired_fps_to_set <= max_fps):
                            log.warning(
                                f"Desired FPS {desired_fps_to_set:.2f} is out of range ({min_fps:.2f}-{max_fps:.2f})."
                            )
                            if (
                                desired_fps_to_set > max_fps and max_fps > 0
                            ):  # Ensure max_fps is sensible
                                desired_fps_to_set = max_fps
                                log.info(
                                    f"Clamping FPS to maximum: {desired_fps_to_set:.2f}"
                                )
                            elif desired_fps_to_set < min_fps:
                                desired_fps_to_set = min_fps
                                log.info(
                                    f"Clamping FPS to minimum: {desired_fps_to_set:.2f}"
                                )
                            else:  # max_fps might be 0 or invalid if camera doesn't support rate control for this format
                                log.warning(
                                    f"Could not clamp FPS {desired_fps_to_set:.2f} as max_fps is {max_fps:.2f}. Frame rate might not be controllable."
                                )

                        if self._is_prop_writable(fps_prop):
                            self._set_property_value(
                                PROP_ACQUISITION_FRAME_RATE, desired_fps_to_set
                            )
                            log.info(
                                f"Actual '{PROP_ACQUISITION_FRAME_RATE}' after setting: {fps_prop.value:.2f}"
                            )
                        else:
                            log.warning(
                                f"'{PROP_ACQUISITION_FRAME_RATE}' is not writable for the current format. Using camera default: {fps_prop.value:.2f} FPS."
                            )

                    except Exception as e_fps_range:
                        log.error(
                            f"Error querying or setting FPS for {PROP_ACQUISITION_FRAME_RATE}: {e_fps_range}",
                            exc_info=True,
                        )
                else:
                    log.warning(
                        f"'{PROP_ACQUISITION_FRAME_RATE}' property not found or not available for current format."
                    )

                # STEP D: Other essential settings
                self._set_property_value(PROP_ACQUISITION_MODE, "Continuous")
                self._set_property_value(PROP_TRIGGER_MODE, "Off")
                # Note: Width, Height, PixelFormat, OffsetX, OffsetY are now primarily controlled by the VideoFormat.
                # It's good practice to log their actual values after setting the video format.
                log.info(
                    f"Camera configured: W={self.pm.find(PROP_WIDTH).value}, H={self.pm.find(PROP_HEIGHT).value}, "
                    f"PF={self.pm.find(PROP_PIXEL_FORMAT).value}, FPS={self.pm.find(PROP_ACQUISITION_FRAME_RATE).value if fps_prop and fps_prop.is_available else 'N/A'}"
                )

            except Exception as e_initial_setup:  # Catch-all for this new setup block
                log.error(
                    f"Critical error during new camera setup phase: {e_initial_setup}",
                    exc_info=True,
                )
                self.camera_error.emit(
                    f"SetupFail: {e_initial_setup}", type(e_initial_setup).__name__
                )
                return  # Cannot proceed

            # push initial state to UI
            self._apply_pending_properties()
            self._emit_available_resolutions()  # Call the OLD method for now to keep UI somewhat populated
            self._emit_camera_properties()

            # push initial state to UI for controls like Exposure, Gain, etc.
            self._apply_pending_properties()  # Apply any exposure/gain changes that were queued before start
            self._emit_camera_properties()  # Update UI with actual ranges for these adjustable properties

            # start sink + streaming
            self.sink = ic4.QueueSink(self.dummy_listener)
            if hasattr(self.sink, "accept_incomplete_frames"):
                self.sink.accept_incomplete_frames = False
            log.info("QueueSink created")

            self.grabber.stream_setup(
                self.sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            log.info("Streaming started")

            frame_count = 0
            no_data_count = 0

            while not self._stop_requested:
                # debounce & apply any pending exposure/gain/etc
                self._apply_pending_properties()

                try:
                    buf = self.sink.pop_output_buffer()
                except ic4.IC4Exception as ex:
                    name = ex.code.name if getattr(ex, "code", None) else ""
                    if "NoData" in name or "Time" in name:
                        no_data_count += 1
                        if no_data_count % 200 == 0:
                            log.warning(f"No frames for ~{no_data_count*0.05:.1f}s")
                        self.msleep(50)
                        continue
                    log.error("Sink pop failed", exc_info=True)
                    self.camera_error.emit(str(ex), name)
                    break

                if buf is None:
                    no_data_count += 1
                    if no_data_count % 200 == 0:
                        log.warning(
                            f"pop_output_buffer returned None for ~{no_data_count*0.05:.1f}s"
                        )
                    self.msleep(50)
                    continue

                frame_count += 1
                no_data_count = 0
                w = buf.image_type.width
                h = buf.image_type.height
                log.info(
                    f"Frame {frame_count}: {w}×{h}, {buf.image_type.pixel_format.name}"
                )

                # extract raw Mono8 bytes
                try:
                    fmt = self.actual_qimage_format
                    stride = w
                    raw = None

                    if hasattr(buf, "numpy_wrap"):
                        arr = buf.numpy_wrap()
                        stride = arr.strides[0]
                        raw = arr.tobytes()
                    elif hasattr(buf, "numpy_copy"):
                        arr = buf.numpy_copy()
                        stride = arr.strides[0]
                        raw = arr.tobytes()
                    elif hasattr(buf, "pointer"):
                        ptr = buf.pointer
                        pitch = getattr(buf, "pitch", w)
                        raw = ctypes.string_at(ptr, pitch * h)
                        stride = pitch
                    else:
                        raise RuntimeError("No image-buffer interface found")

                    img = QImage(raw, w, h, stride, fmt)
                    if img.isNull():
                        log.warning("Built QImage is null")
                    else:
                        self.frame_ready.emit(img.copy(), raw)

                except Exception:
                    log.error("QImage construction failed", exc_info=True)

            log.info("Exited acquisition loop")

        except Exception:
            log.exception("Unhandled in run()")
            self.camera_error.emit("Unexpected", "Exception")

        finally:
            log.info("Shutting down grabber")
            if self.grabber:
                try:
                    if self.grabber.is_streaming:
                        self.grabber.stream_stop()
                        log.info("Stream stopped")
                except Exception:
                    pass
                try:
                    if self.grabber.is_device_open:
                        self.grabber.device_close()
                        log.info("Device closed")
                except Exception:
                    pass
            self.grabber = self.sink = self.pm = None
            log.info("SDKCameraThread fully stopped")
