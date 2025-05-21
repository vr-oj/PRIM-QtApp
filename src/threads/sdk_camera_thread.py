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

        # user-requested parameters
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

        # for video-format selection
        self.selected_video_format_identifier = None

    def request_stop(self):
        self._stop_requested = True

    # GUI thread slots
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

            dummy_id = f"current_{w}x{h}_{pf_name.replace(' ','_')}"
            display_text = f"{w}x{h} ({pf_name})"

            log.info(
                f"Emitting fallback video format option: {display_text} (ID: {dummy_id})"
            )
            self.camera_video_formats_available.emit(
                [{"text": display_text, "id": dummy_id}]
            )

            if not self.selected_video_format_identifier:
                self.selected_video_format_identifier = dummy_id
                log.info(
                    f" Set selected_video_format_identifier to fallback: {dummy_id}"
                )

        except Exception as e:
            log.error(
                f"Failed to emit current settings as format option: {e}", exc_info=True
            )
            self.camera_video_formats_available.emit([])

    def _emit_available_resolutions(self):
        if not self.pm:
            self.camera_resolutions_available.emit([])
            return
        try:
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
                    "One or more properties (Width, Height, PixelFormat) not available for _emit_available_resolutions."
                )
                self.camera_resolutions_available.emit([])
                return

            w = w_prop.value
            h = h_prop.value
            pf_val = pf_prop.value

            pf_name = ""
            if hasattr(pf_val, "name"):
                pf_name = pf_val.name
            elif isinstance(pf_val, str):
                pf_name = pf_val
            else:
                pf_name = str(pf_val)
                log.warning(
                    f"PixelFormat value is not standard: {pf_val}. Using str()."
                )

            resolution_string = f"{w}x{h} ({pf_name})"
            self.camera_resolutions_available.emit([resolution_string])
            log.debug(f"Emitted available resolution: {resolution_string}")

        except Exception as e:
            log.warning(
                f"Could not list resolutions: {e}",
                exc_info=True,
            )
            self.camera_resolutions_available.emit([])

    def _enumerate_video_formats(self):
        """
        Ask the SDK for its complete VideoFormatDesc list,
        then emit them as a list of {'id': name, 'text': description}.
        """
        try:
            descs = self.grabber.device_info.video_format_descs
            options = []
            for d in descs:
                min_w, min_h = d.min_size.width, d.min_size.height
                max_w, max_h = d.max_size.width, d.max_size.height
                txt = f"{d.name}: {min_w}×{min_h} → {max_w}×{max_h}"
                options.append({"id": d.name, "text": txt})
            log.info(f"Discovered {len(options)} video formats")
            self.camera_video_formats_available.emit(options)
        except Exception as ex:
            log.error(f"Failed to enumerate video formats: {ex}", exc_info=True)
            self.camera_video_formats_available.emit([])

    def run(self):
        log.info(
            f"SDKCameraThread starting for {self.device_info.model_name if self.device_info else 'Unknown'}"
        )
        self.grabber = ic4.Grabber()
        try:
            if not self.device_info:
                devs = ic4.DeviceEnum.devices()
                if not devs:
                    raise RuntimeError("No cameras found")
                self.device_info = devs[0]
                log.info(
                    f"No device_info provided, selected first device: {self.device_info.model_name}"
                )

            log.info(f"Attempting to open device: {self.device_info.model_name}")
            self.grabber.device_open(self.device_info)
            self.pm = self.grabber.device_property_map
            log.info(f"Opened {self.device_info.model_name} successfully.")

            # Enumerate & emit all SDK-defined video formats
            self._enumerate_video_formats()

            # Apply user-selected format if any
            if self.selected_video_format_identifier:
                descs = self.grabber.device_info.video_format_descs
                chosen = next(
                    (
                        d
                        for d in descs
                        if d.name == self.selected_video_format_identifier
                    ),
                    None,
                )
                if chosen:
                    log.info(f"Applying user-selected video format: {chosen.name}")
                    chosen.create_video_format()
                else:
                    log.warning(
                        f"Selected format ID '{self.selected_video_format_identifier}' not found."
                    )

            # === Simplified default + FPS clamp setup ===
            log.info(
                "Attempting simplified setup using camera defaults and FPS clamping."
            )
            try:
                wp = self.pm.find(PROP_WIDTH)
                hp = self.pm.find(PROP_HEIGHT)
                pfp = self.pm.find(PROP_PIXEL_FORMAT)

                initial_w = wp.value if wp and wp.is_available else "N/A"
                initial_h = hp.value if hp and hp.is_available else "N/A"
                initial_pf_val = pfp.value if pfp and pfp.is_available else "N/A"

                initial_pf_name = initial_pf_val
                if hasattr(initial_pf_val, "name"):
                    initial_pf_name = initial_pf_val.name
                elif isinstance(initial_pf_val, str):
                    initial_pf_name = initial_pf_val
                else:
                    initial_pf_name = str(initial_pf_val)

                log.info(
                    f"Camera default state: W={initial_w}, H={initial_h}, PF='{initial_pf_name}'"
                )

                current_pf_name_lower = initial_pf_name.lower()
                if "mono8" in current_pf_name_lower:
                    self.actual_qimage_format = QImage.Format_Grayscale8
                    log.info(
                        f"QImage format set to Grayscale8 for PF: {initial_pf_name}"
                    )
                elif "bayer" in current_pf_name_lower:
                    self.actual_qimage_format = QImage.Format_RGB888
                    log.info(
                        f"QImage format set for potential RGB (from Bayer PF: {initial_pf_name})"
                    )
                else:
                    log.warning(
                        f"Default PixelFormat '{initial_pf_name}' not explicitly handled for QImage. Defaulting to Grayscale8."
                    )
                    self.actual_qimage_format = QImage.Format_Grayscale8

                fps_prop = self.pm.find(PROP_ACQUISITION_FRAME_RATE)
                desired_fps_to_set = float(self.target_fps)

                if fps_prop and fps_prop.is_available:
                    try:
                        min_fps = fps_prop.minimum
                        max_fps = fps_prop.maximum
                        log.info(
                            f"Property '{PROP_ACQUISITION_FRAME_RATE}' valid range (default format): {min_fps:.2f} - {max_fps:.2f} FPS"
                        )

                        if not (min_fps <= desired_fps_to_set <= max_fps):
                            log.warning(
                                f"Desired FPS {desired_fps_to_set:.2f} is out of range ({min_fps:.2f}-{max_fps:.2f})."
                            )
                            if desired_fps_to_set > max_fps and max_fps > 0:
                                desired_fps_to_set = max_fps
                                log.info(
                                    f"Clamping FPS to maximum: {desired_fps_to_set:.2f}"
                                )
                            elif desired_fps_to_set < min_fps:
                                desired_fps_to_set = min_fps
                                log.info(
                                    f"Clamping FPS to minimum: {desired_fps_to_set:.2f}"
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
                                f"'{PROP_ACQUISITION_FRAME_RATE}' is not writable. Using camera default: {fps_prop.value:.2f} FPS."
                            )
                    except Exception as e_fps_details:
                        log.error(
                            f"Error getting FPS details or setting FPS: {e_fps_details}",
                            exc_info=True,
                        )
                else:
                    log.warning(
                        f"'{PROP_ACQUISITION_FRAME_RATE}' property not found or not available."
                    )

                self._set_property_value(PROP_ACQUISITION_MODE, "Continuous")
                self._set_property_value(PROP_TRIGGER_MODE, "Off")

                log.info(
                    f"Camera configured (simplified): W={self.pm.find(PROP_WIDTH).value}, H={self.pm.find(PROP_HEIGHT).value}, "
                    f"PF='{self.pm.find(PROP_PIXEL_FORMAT).value}', FPS={self.pm.find(PROP_ACQUISITION_FRAME_RATE).value if fps_prop and fps_prop.is_available else 'N/A'}"
                )

            except Exception as e_initial_setup:
                log.error(
                    f"Critical error during simplified camera setup phase: {e_initial_setup}",
                    exc_info=True,
                )
                self.camera_error.emit(
                    f"SimplifiedSetupFail: {e_initial_setup}",
                    type(e_initial_setup).__name__,
                )
                return

            # push initial state to UI
            self._apply_pending_properties()
            self._emit_available_resolutions()
            self._emit_camera_properties()

            # start sink + streaming
            self.sink = ic4.QueueSink(self.dummy_listener)
            self.sink.timeout = 200
            if hasattr(self.sink, "accept_incomplete_frames"):
                self.sink.accept_incomplete_frames = False
            log.info("QueueSink created with 200ms timeout.")

            self.grabber.stream_setup(
                self.sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            log.info("Streaming started")

            frame_count = 0
            no_data_count = 0

            while not self._stop_requested:
                self._apply_pending_properties()

                try:
                    buf = self.sink.pop_output_buffer()

                except ic4.IC4Exception as ex:
                    if ex.code == ic4.ErrorCode.Timeout:
                        no_data_count += 1
                        if no_data_count % 25 == 0:
                            log.warning(
                                f"pop_output_buffer timed out ({self.sink.timeout}ms). Total timeouts: {no_data_count}"
                            )
                        self.msleep(20)
                        continue

                    name = ex.code.name if getattr(ex, "code", None) else ""
                    if "NoData" in name or "Time" in name:
                        no_data_count += 1
                        if no_data_count % 100 == 0:
                            log.warning(
                                f"No frames (IC4Exception {name}) for ~{no_data_count*0.05:.1f}s"
                            )
                        self.msleep(50)
                        continue
                    log.error(
                        f"Sink pop failed with IC4Exception: {ex} (Code: {name})",
                        exc_info=True,
                    )
                    self.camera_error.emit(str(ex), name)
                    break

                if buf is None:
                    no_data_count += 1
                    if no_data_count % 100 == 0:
                        log.warning(
                            f"pop_output_buffer returned None (no IC4Exception.Timeout) for ~{no_data_count*0.05:.1f}s"
                        )
                    self.msleep(50)
                    continue

                if not buf.is_valid:
                    log.warning(
                        f"Popped buffer (ID: {buf.image_id_device if hasattr(buf, 'image_id_device') else 'N/A'}) is not valid. Skipping."
                    )
                    self.msleep(1)
                    continue

                frame_count += 1
                no_data_count = 0
                w = buf.image_type.width
                h = buf.image_type.height
                log.info(
                    f"Frame {frame_count}: {w}×{h}, {buf.image_type.pixel_format.name}"
                )

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
                        pitch = getattr(
                            buf, "pitch", w * buf.image_type.bytes_per_pixel
                        )
                        raw = ctypes.string_at(ptr, pitch * h)
                        stride = pitch
                    else:
                        log.error(
                            "No image-buffer interface (numpy_wrap, numpy_copy, or pointer) found on buffer."
                        )
                        raise RuntimeError("No image-buffer interface found")

                    if raw:
                        img = QImage(raw, w, h, stride, fmt)
                        if img.isNull():
                            log.warning("Built QImage is null")
                        else:
                            self.frame_ready.emit(img.copy(), raw)
                    else:
                        log.warning("Raw data could not be extracted from buffer.")

                except Exception as e_img_conv:
                    log.error(
                        f"QImage construction or data extraction failed: {e_img_conv}",
                        exc_info=True,
                    )

        except Exception as e_unhandled:
            log.exception(
                f"Unhandled exception in SDKCameraThread.run(): {e_unhandled}"
            )
            self.camera_error.emit(
                f"Unexpected: {e_unhandled}", type(e_unhandled).__name__
            )

        finally:
            log.info("Shutting down grabber in SDKCameraThread.run() finally block")
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
