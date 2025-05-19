import logging
import time
import ctypes
import imagingcontrol4 as ic4

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

from imagingcontrol4.properties import (
    PropInteger,
    PropFloat,
    PropEnumeration,
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
            f"DummyListener: Sink connected. {image_type}, MinBuffers={min_buffers_required}"
        )
        return True

    def frames_queued(self, sink):
        pass

    def sink_disconnected(self, sink):
        log.debug(f"DummyListener: Sink disconnected ({type(sink)})")


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

        # throttle applying camera‐properties (sec)
        self._prop_throttle_interval = 0.1
        self._last_prop_apply_time = 0.0

        # runtime state
        self.grabber = None
        self.sink = None
        self.pm = None
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
        # throttle so we only ever hit the driver ~10×/s at most
        now = time.monotonic()
        any_pending = any(
            x is not None
            for x in (
                self._pending_auto_exposure,
                self._pending_exposure_us,
                self._pending_gain_db,
                self._pending_roi,
            )
        )
        if not any_pending:
            return
        if now - self._last_prop_apply_time < self._prop_throttle_interval:
            return
        self._last_prop_apply_time = now

        if not (self.pm and self.grabber and self.grabber.is_device_open):
            return

        # auto exposure toggle
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
                    self._emit_camera_properties()
            self._pending_auto_exposure = None

        # manual exposure
        if self._pending_exposure_us is not None:
            pa = self.pm.find(PROP_EXPOSURE_AUTO)
            auto_on = False
            if pa and pa.is_available:
                v = pa.value
                auto_on = (v != "Off") if isinstance(v, str) else bool(v)
            if not auto_on:
                self._set_property_value(PROP_EXPOSURE_TIME, self._pending_exposure_us)
            self._pending_exposure_us = None

        # gain
        if self._pending_gain_db is not None:
            self._set_property_value(PROP_GAIN, self._pending_gain_db)
            self._pending_gain_db = None

        # ROI (offset)
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

        d = {"controls": {}, "roi": {}}

        # exposure & gain
        for key, (pv, pa) in {
            "exposure": (PROP_EXPOSURE_TIME, PROP_EXPOSURE_AUTO),
            "gain": (PROP_GAIN, None),
        }.items():
            info = {"enabled": False, "value": 0, "min": 0, "max": 0}
            try:
                prop = self.pm.find(pv)
                if prop and prop.is_available:
                    info["enabled"] = self._is_prop_writable(prop)
                    if isinstance(prop, (PropInteger, PropFloat)):
                        info.update(
                            min=prop.minimum, max=prop.maximum, value=prop.value
                        )
                    elif isinstance(prop, PropEnumeration):
                        info.update(
                            options=[e.name for e in prop.entries], value=prop.value
                        )
                    if pa:
                        pa_prop = self.pm.find(pa)
                        if pa_prop and pa_prop.is_available:
                            av = pa_prop.value
                            is_auto = (av != "Off") if isinstance(av, str) else bool(av)
                            info["auto_available"] = True
                            info["is_auto_on"] = is_auto
                            if key == "exposure" and is_auto:
                                info["enabled"] = False
            except Exception:
                pass
            d["controls"][key] = info

        # ROI
        try:
            roi = {}
            for k, nm in [
                ("w", PROP_WIDTH),
                ("h", PROP_HEIGHT),
                ("x", PROP_OFFSET_X),
                ("y", PROP_OFFSET_Y),
            ]:
                p = self.pm.find(nm)
                roi[k] = p.value
                if hasattr(p, "maximum"):
                    roi["max_" + k] = p.maximum
            d["roi"] = roi
        except Exception:
            pass

        self.camera_properties_updated.emit(d)

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
            log.warning(f"Couldn’t list resolutions: {e}")
            self.camera_resolutions_available.emit([])

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

            # ── initial setup ─────────────────────────────────
            try:
                # force Mono8
                pfp = self.pm.find(PROP_PIXEL_FORMAT)
                cur_pf = pfp.value
                want_pf = self.desired_pixel_format_str
                if isinstance(pfp, PropEnumeration) and cur_pf.lower().replace(
                    " ", ""
                ) != want_pf.lower().replace(" ", ""):
                    opts = [e.name for e in pfp.entries]
                    if want_pf in opts:
                        self._set_property_value(PROP_PIXEL_FORMAT, want_pf)
                    else:
                        want_pf = cur_pf
                self.actual_qimage_format = QImage.Format_Grayscale8

                # full‐sensor resolution
                wp = self.pm.find(PROP_WIDTH)
                hp = self.pm.find(PROP_HEIGHT)
                if wp and wp.is_available and self._is_prop_writable(wp):
                    self._set_property_value(PROP_WIDTH, wp.maximum)
                if hp and hp.is_available and self._is_prop_writable(hp):
                    self._set_property_value(PROP_HEIGHT, hp.maximum)

                # reset any ROI
                self._set_property_value(PROP_OFFSET_X, 0)
                self._set_property_value(PROP_OFFSET_Y, 0)

                log.info(
                    f"Res: {wp.value}×{hp.value}, PF={self.pm.find(PROP_PIXEL_FORMAT).value}"
                )

                # streaming params
                self._set_property_value(PROP_ACQUISITION_MODE, "Continuous")
                self._set_property_value(PROP_TRIGGER_MODE, "Off")
                self._set_property_value(
                    PROP_ACQUISITION_FRAME_RATE, float(self.target_fps)
                )
            except Exception as e:
                log.error("Config failed", exc_info=True)
                self.camera_error.emit(f"Config: {e}", type(e).__name__)
                return

            # initial UI push
            self._apply_pending_properties()
            self._emit_available_resolutions()
            self._emit_camera_properties()

            # build sink
            self.sink = ic4.QueueSink(self.dummy_listener)
            if hasattr(self.sink, "accept_incomplete_frames"):
                self.sink.accept_incomplete_frames = False
            log.info("QueueSink created")

            # start stream
            self.grabber.stream_setup(
                self.sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            log.info("Streaming started")

            last = time.monotonic()
            frame_count = 0
            no_data_count = 0

            while not self._stop_requested:
                # only apply properties at most 10×/s
                self._apply_pending_properties()

                # pull next frame
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

                    # 1) numpy_wrap
                    if hasattr(buf, "numpy_wrap"):
                        arr = buf.numpy_wrap()
                        stride = arr.strides[0]
                        raw = arr.tobytes()

                    # 2) numpy_copy
                    elif hasattr(buf, "numpy_copy"):
                        arr = buf.numpy_copy()
                        stride = arr.strides[0]
                        raw = arr.tobytes()

                    # 3) pointer + pitch
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

                # pace to target FPS
                now = time.monotonic()
                dt = now - last
                target = 1.0 / self.target_fps if self.target_fps > 0 else 0.05
                if dt < target:
                    self.msleep(int((target - dt) * 1000))
                last = time.monotonic()

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
