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
from config import DEFAULT_FRAME_SIZE

log = logging.getLogger(__name__)

# camera‐property names
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

    # The QueueSink now only passes one argument here (the sink),
    # so we drop the userdata parameter.
    def frames_queued(self, sink):
        # nothing to do
        pass

    def sink_disconnected(self, sink):
        log.debug(f"DummyListener: Sink disconnected (sink={type(sink)}).")


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

        # pending property updates
        self._pending_exposure_us = None
        self._pending_gain_db = None
        self._pending_auto_exposure = None
        self._pending_roi = None

        # runtime state
        self.grabber = None
        self.sink = None
        self.pm = None
        self.current_frame_width = 0
        self.current_frame_height = 0
        self.current_pixel_format_name = ""
        self.actual_qimage_format = QImage.Format_Invalid

        self.dummy_listener = DummySinkListener()

    def request_stop(self):
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
        return bool(
            prop_object
            and prop_object.is_available
            and not getattr(prop_object, "is_readonly", True)
        )

    def _set_property_value(self, prop_name: str, value_to_set):
        try:
            prop = self.pm.find(prop_name)
            if self._is_prop_writable(prop):
                self.pm.set_value(prop_name, value_to_set)
                log.info(f"Set {prop.name} to {value_to_set}")
                return True
            elif prop and prop.is_available:
                log.warning(f"Prop {prop.name} not writable (readonly).")
        except Exception as e:
            log.warning(f"Error setting {prop_name}: {e}")
        return False

    def _apply_pending_properties(self):
        if not (self.pm and self.grabber and self.grabber.is_device_open):
            return

        # auto exposure on/off
        if self._pending_auto_exposure is not None:
            prop_auto = self.pm.find(PROP_EXPOSURE_AUTO)
            if prop_auto and prop_auto.is_available:
                val = "Continuous" if self._pending_auto_exposure else "Off"
                self._set_property_value(
                    PROP_EXPOSURE_AUTO,
                    (
                        val
                        if isinstance(prop_auto, PropEnumeration)
                        else self._pending_auto_exposure
                    ),
                )
                # if turning auto off, emit updated exposure range
                if not self._pending_auto_exposure:
                    self._emit_camera_properties()
            self._pending_auto_exposure = None

        # manual exposure time
        if self._pending_exposure_us is not None:
            prop_auto = self.pm.find(PROP_EXPOSURE_AUTO)
            auto_on = False
            if prop_auto and prop_auto.is_available:
                v = prop_auto.value
                auto_on = (v != "Off") if isinstance(v, str) else bool(v)
            if not auto_on:
                self._set_property_value(PROP_EXPOSURE_TIME, self._pending_exposure_us)
            self._pending_exposure_us = None

        # gain
        if self._pending_gain_db is not None:
            self._set_property_value(PROP_GAIN, self._pending_gain_db)
            self._pending_gain_db = None

        # ROI (offset x/y)
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

        props_dict = {"controls": {}, "roi": {}}

        # exposure & gain controls
        for key, (pn_val, pn_auto) in {
            "exposure": (PROP_EXPOSURE_TIME, PROP_EXPOSURE_AUTO),
            "gain": (PROP_GAIN, None),
        }.items():
            info = {"enabled": False, "value": 0, "min": 0, "max": 0}
            try:
                pv = self.pm.find(pn_val)
                if pv and pv.is_available:
                    info["enabled"] = self._is_prop_writable(pv)
                    if isinstance(pv, PropInteger) or isinstance(pv, PropFloat):
                        info.update(min=pv.minimum, max=pv.maximum, value=pv.value)
                    elif isinstance(pv, PropEnumeration):
                        info.update(
                            options=[e.name for e in pv.entries], value=pv.value
                        )
                    if pn_auto:
                        pa = self.pm.find(pn_auto)
                        if pa and pa.is_available:
                            av = pa.value
                            is_auto = (av != "Off") if isinstance(av, str) else bool(av)
                            info["auto_available"] = True
                            info["is_auto_on"] = is_auto
                            if key == "exposure" and is_auto:
                                info["enabled"] = False
            except Exception:
                pass
            props_dict["controls"][key] = info

        # ROI properties
        roi_props = {}
        try:
            for attr_key, pn in [
                ("w", PROP_WIDTH),
                ("h", PROP_HEIGHT),
                ("x", PROP_OFFSET_X),
                ("y", PROP_OFFSET_Y),
            ]:
                p = self.pm.find(pn)
                roi_props[attr_key] = p.value
                if hasattr(p, "maximum"):
                    roi_props["max_" + attr_key] = p.maximum
        except Exception:
            pass
        props_dict["roi"] = roi_props

        self.camera_properties_updated.emit(props_dict)

    def _emit_available_resolutions(self):
        if not self.pm:
            self.camera_resolutions_available.emit([])
            return
        try:
            w = self.pm.find(PROP_WIDTH).value
            h = self.pm.find(PROP_HEIGHT).value
            pf = self.pm.find(PROP_PIXEL_FORMAT).value
            self.camera_resolutions_available.emit([f"{w}x{h} ({pf})"])
        except Exception as e:
            log.warning(f"Error emitting resolutions: {e}")
            self.camera_resolutions_available.emit([])

    def run(self):
        log.info(
            f"SDKCameraThread starting for: {self.device_info.model_name or 'Unknown'}"
        )
        self.grabber = ic4.Grabber()
        try:
            # choose first TIS camera if none provided
            if not self.device_info:
                devices = ic4.DeviceEnum.devices()
                if not devices:
                    raise RuntimeError("No TIS cameras found.")
                self.device_info = devices[0]

            self.grabber.device_open(self.device_info)
            self.pm = self.grabber.device_property_map
            log.info(f"Device opened: {self.device_info.model_name}")

            # ── initial configuration ────────────────────────────
            try:
                # force Mono8 pixel format
                pf_prop = self.pm.find(PROP_PIXEL_FORMAT)
                current_pf = pf_prop.value
                desired_pf = self.desired_pixel_format_str
                if isinstance(pf_prop, PropEnumeration) and current_pf.lower().replace(
                    " ", ""
                ) != desired_pf.lower().replace(" ", ""):
                    opts = [e.name for e in pf_prop.entries]
                    if desired_pf in opts:
                        self._set_property_value(PROP_PIXEL_FORMAT, desired_pf)
                    else:
                        # fallback to whatever is available
                        desired_pf = current_pf
                self.current_pixel_format_name = self.pm.find(PROP_PIXEL_FORMAT).value
                if self.current_pixel_format_name.replace(" ", "") != "Mono8":
                    raise RuntimeError(
                        f"Not Mono8 format ({self.current_pixel_format_name})"
                    )
                self.actual_qimage_format = QImage.Format_Grayscale8

                # width / height
                w_prop = self.pm.find(PROP_WIDTH)
                h_prop = self.pm.find(PROP_HEIGHT)
                if self.desired_width and self._is_prop_writable(w_prop):
                    self._set_property_value(PROP_WIDTH, self.desired_width)
                if self.desired_height and self._is_prop_writable(h_prop):
                    self._set_property_value(PROP_HEIGHT, self.desired_height)
                self.current_frame_width = (
                    w_prop.value
                    if (w_prop and w_prop.is_available)
                    else DEFAULT_FRAME_SIZE[0]
                )
                self.current_frame_height = (
                    h_prop.value
                    if (h_prop and h_prop.is_available)
                    else DEFAULT_FRAME_SIZE[1]
                )
                log.info(
                    f"Res: {self.current_frame_width}x{self.current_frame_height}, Format: {self.current_pixel_format_name}"
                )

                # acquisition setup
                self._set_property_value(PROP_ACQUISITION_MODE, "Continuous")
                self._set_property_value(PROP_TRIGGER_MODE, "Off")
                self._set_property_value(
                    PROP_ACQUISITION_FRAME_RATE, float(self.target_fps)
                )
            except Exception as e:
                log.error("Config error", exc_info=True)
                self.camera_error.emit(f"Config: {e}", type(e).__name__)
                return

            # push initial UI state
            self._apply_pending_properties()
            self._emit_available_resolutions()
            self._emit_camera_properties()

            # build our sink
            self.sink = ic4.QueueSink(self.dummy_listener)
            if hasattr(self.sink, "accept_incomplete_frames"):
                self.sink.accept_incomplete_frames = False
            log.info("QueueSink created.")

            # *** FIX: pass None for the Display parameter ***
            self.grabber.stream_setup(
                None, self.sink, ic4.StreamSetupOption.ACQUISITION_START
            )
            log.info("Stream setup with ACQUISITION_START attempted.")
            log.info("Entering frame acquisition loop...")

            fc = 0
            nbc = 0
            last_ft = time.monotonic()

            while not self._stop_requested:
                self._apply_pending_properties()

                try:
                    buf = self.sink.pop_output_buffer()
                except ic4.IC4Exception as e_pop:
                    # extract the enum member name
                    code_name = getattr(e_pop, "code", None)
                    code_name = code_name.name if code_name else ""
                    # treat NoData and timeout both as "no frame yet"
                    if "NoData" in code_name or "Time" in code_name:
                        nbc += 1
                        if nbc % 200 == 0:
                            sec = nbc * 0.05
                            log.warning(f"No frames after ~{sec:.1f}s of polling.")
                        self.msleep(50)
                        continue
                    # unexpected error
                    log.error("IC4Exception during pop_output_buffer", exc_info=True)
                    self.camera_error.emit(str(e_pop), f"SinkPop ({code_name})")
                    break

                if buf is None:
                    nbc += 1
                    if nbc % 200 == 0:
                        sec = nbc * 0.05
                        log.warning(
                            f"pop_output_buffer returned None after ~{sec:.1f}s"
                        )
                    self.msleep(50)
                    continue

                # got a valid buffer
                fc += 1
                log.info(
                    f"Frame {fc}: W={buf.image_type.width}, H={buf.image_type.height}, Fmt={buf.image_type.pixel_format.name}"
                )
                nbc = 0

                # build a QImage directly from the buffer
                try:
                    # FIX: new API uses .buffer_ptr (or .buffer) instead of .mem_ptr
                    if hasattr(buf, "buffer_ptr"):
                        ptr = buf.buffer_ptr
                    elif hasattr(buf, "mem_ptr"):
                        ptr = buf.mem_ptr
                    elif hasattr(buf, "buffer"):
                        ptr = buf.buffer
                    else:
                        raise AttributeError(
                            "Cannot find buffer pointer on ImageBuffer"
                        )

                    img = QImage(
                        ptr,
                        buf.image_type.width,
                        buf.image_type.height,
                        buf.image_type.stride_bytes,
                        self.actual_qimage_format,
                    )
                    if not img.isNull():
                        self.frame_ready.emit(img.copy(), ptr)
                    else:
                        log.warning(f"Frame {fc}: QImage isNull.")
                except Exception as e_img:
                    log.error(f"Error constructing QImage: {e_img}", exc_info=True)

                # pace ourselves
                now = time.monotonic()
                dt = now - last_ft
                target_interval = 1.0 / self.target_fps if self.target_fps > 0 else 0.05
                if dt < target_interval:
                    self.msleep(int((target_interval - dt) * 1000))
                last_ft = time.monotonic()

            log.info("Exited frame acquisition loop.")

        except Exception as e:
            log.exception("Unhandled exception in SDKCameraThread.run()")
            self.camera_error.emit(str(e), type(e).__name__)

        finally:
            log.info("SDKCameraThread run() finishing...")
            if self.grabber:
                try:
                    if self.grabber.is_streaming:
                        self.grabber.stream_stop()
                        log.info("Stream stopped.")
                except Exception:
                    pass
                try:
                    if self.grabber.is_device_open:
                        self.grabber.device_close()
                        log.info("Device closed.")
                except Exception:
                    pass
            self.grabber = self.sink = self.pm = None
            log.info(
                f"SDKCameraThread ({self.device_info.model_name if self.device_info else 'N/A'}) fully stopped."
            )
