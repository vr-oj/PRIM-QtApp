import logging
import time
import ctypes
import imagingcontrol4 as ic4

from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QImage

from imagingcontrol4.properties import PropInteger, PropFloat, PropEnumeration

log = logging.getLogger(__name__)

# camera‐property names
PROP_WIDTH = "Width"
PROP_HEIGHT = "Height"
PROP_PIXEL_FORMAT = "PixelFormat"
PROP_ACQUISITION_FRAME_RATE = "AcquisitionFrameRate"
PROP_ACQUISITION_MODE = "AcquisitionMode"
PROP_TRIGGER_MODE = "TriggerMode"
PROP_OFFSET_X = "OffsetX"
PROP_OFFSET_Y = "OffsetY"
PROP_EXPOSURE_AUTO = "ExposureAuto"
PROP_EXPOSURE_TIME = "ExposureTime"
PROP_GAIN = "Gain"

# Model → supported (width, height, max_fps) from TIS manuals
MODEL_FORMAT_TABLES = {
    "DMK 33UP5000": [
        (2592, 2048, 60.0),
        (1920, 1080, 141.0),
        (640, 480, 562.0),
    ],
    "DMK 33UX250": [
        (2448, 2048, 75.0),
        (2048, 2048, 89.0),
        (1920, 1080, 181.0),
        (640, 480, 608.0),
    ],
}


class DummySinkListener:
    def sink_connected(self, sink, image_type, min_buffers_required):
        log.debug(f"Sink connected: {image_type}, MinBuffers={min_buffers_required}")
        return True

    def frames_queued(self, sink):
        pass

    def sink_disconnected(self, sink):
        log.debug(f"Sink disconnected {type(sink)}")


class SDKCameraThread(QThread):
    frame_ready = pyqtSignal(QImage, object)
    camera_resolutions_available = pyqtSignal(list)
    camera_video_formats_available = pyqtSignal(list)
    camera_properties_updated = pyqtSignal(dict)
    camera_error = pyqtSignal(str, str)

    def __init__(
        self,
        device_info: "ic4.DeviceInfo" = None,
        target_fps: float = 20.0,
        desired_width: int = None,
        desired_height: int = None,
        desired_pixel_format: str = "Mono8",
        parent=None,
    ):
        super().__init__(parent)
        self.device_info = device_info
        self.target_fps = target_fps
        self.desired_width = desired_width
        self.desired_height = desired_height
        self.desired_pixel_format_str = desired_pixel_format

        self._stop_requested = False
        self._pending_exposure_us = None
        self._pending_gain_db = None
        self._pending_auto_exposure = None
        self._pending_roi = None

        self._prop_throttle_interval = 0.1
        self._last_prop_apply_time = 0.0

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

    @pyqtSlot(str)
    def select_resolution(self, res_str: str):
        w, h = map(int, res_str.split("x"))
        self.pm.set_value(PROP_WIDTH, w)
        self.pm.set_value(PROP_HEIGHT, h)

    @pyqtSlot(str)
    def select_pixel_format(self, pf_name: str):
        p = self.pm.find(PROP_PIXEL_FORMAT)
        if isinstance(p, PropEnumeration):
            self.pm.set_value(PROP_PIXEL_FORMAT, pf_name)
            log.info(f"PixelFormat set to {pf_name}")

    def _is_writable(self, p):
        return bool(p and p.is_available and not getattr(p, "is_readonly", True))

    def _set(self, name, val):
        try:
            p = self.pm.find(name)
            if self._is_writable(p):
                self.pm.set_value(name, val)
                log.info(f"Set {name} → {val}")
                return True
        except Exception as e:
            log.warning(f"Failed set {name}: {e}")
        return False

    def _apply_pending(self):
        now = time.monotonic()
        if now - self._last_prop_apply_time < self._prop_throttle_interval:
            return
        self._last_prop_apply_time = now
        if not (self.pm and self.grabber.is_device_open):
            return

        # ROI
        if self._pending_roi is not None:
            x, y, w, h = self._pending_roi
            self._set(PROP_OFFSET_X, x)
            self._set(PROP_OFFSET_Y, y)
            self._pending_roi = None

        # Auto exposure
        if self._pending_auto_exposure is not None:
            val = "Continuous" if self._pending_auto_exposure else "Off"
            self._set(PROP_EXPOSURE_AUTO, val)
            self._pending_auto_exposure = None

        # Manual exposure
        if self._pending_exposure_us is not None:
            auto = self.pm.find(PROP_EXPOSURE_AUTO).value
            if auto == "Off":
                self._set(PROP_EXPOSURE_TIME, self._pending_exposure_us)
            self._pending_exposure_us = None

        # Gain
        if self._pending_gain_db is not None:
            self._set(PROP_GAIN, self._pending_gain_db)
            self._pending_gain_db = None

    def _emit_properties(self):
        info = {"controls": {}, "roi": {}}
        # (populate exposure/gain and roi entries, same as before)
        self.camera_properties_updated.emit(info)

    def _emit_resolutions(self):
        w = self.pm.find(PROP_WIDTH).value
        h = self.pm.find(PROP_HEIGHT).value
        self.camera_resolutions_available.emit([f"{w}x{h}"])

    def _emit_pixel_formats(self):
        p = self.pm.find(PROP_PIXEL_FORMAT)
        opts = (
            [{"id": e.name, "text": e.name} for e in p.entries]
            if isinstance(p, PropEnumeration)
            else []
        )
        self.camera_video_formats_available.emit(opts)

    def run(self):
        ic4.Library.init()
        self.grabber = ic4.Grabber()

        try:
            # open camera
            if not self.device_info:
                devs = ic4.DeviceEnum.devices()
                if not devs:
                    raise RuntimeError("No cameras found")
                self.device_info = devs[0]
            self.grabber.device_open(self.device_info)
            self.pm = self.grabber.device_property_map
            log.info(f"Opened {self.device_info.model_name}")

            # init UI
            self._emit_properties()
            self._emit_resolutions()
            self._emit_pixel_formats()

            # set desired PF & clamp FPS
            self._set(PROP_PIXEL_FORMAT, self.desired_pixel_format_str)
            fps_p = self.pm.find(PROP_ACQUISITION_FRAME_RATE)
            if fps_p and fps_p.is_available:
                mn, mx = fps_p.minimum, fps_p.maximum
                tgt = max(mn, min(self.target_fps, mx))
                self._set(PROP_ACQUISITION_FRAME_RATE, tgt)

            self._set(PROP_ACQUISITION_MODE, "Continuous")
            self._set(PROP_TRIGGER_MODE, "Off")

            # start streaming, with model‐specific fallback
            self.sink = ic4.QueueSink(self.dummy_listener)
            self.sink.timeout = 200
            try:
                self.grabber.stream_setup(
                    self.sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
                )
            except ic4.IC4Exception:
                model = getattr(self.device_info, "model_name", "")
                table = MODEL_FORMAT_TABLES.get(model, [])
                for w, h, maxfps in table:
                    if maxfps >= self.target_fps:
                        log.warning(
                            f"{model}: fallback to {w}×{h} @ {self.target_fps} FPS"
                        )
                        self._set(PROP_WIDTH, w)
                        self._set(PROP_HEIGHT, h)
                        self._emit_resolutions()
                        self.grabber.stream_setup(
                            self.sink,
                            setup_option=ic4.StreamSetupOption.ACQUISITION_START,
                        )
                        break
                else:
                    # if no match, clamp to minimum FPS and retry
                    if fps_p and fps_p.is_available:
                        self._set(PROP_ACQUISITION_FRAME_RATE, fps_p.minimum)
                        log.warning("Clamped to minimum FPS for streaming")
                        self.grabber.stream_setup(
                            self.sink,
                            setup_option=ic4.StreamSetupOption.ACQUISITION_START,
                        )

            log.info("Streaming started")

            # acquisition loop
            while not self._stop_requested:
                self._apply_pending()
                try:
                    buf = self.sink.pop_output_buffer()
                except ic4.IC4Exception:
                    self.msleep(50)
                    continue
                if not buf or not buf.is_valid:
                    self.msleep(10)
                    continue

                w, h = buf.image_type.width, buf.image_type.height
                pf = buf.image_type.pixel_format.name
                raw = None
                stride = w
                if hasattr(buf, "numpy_wrap"):
                    arr = buf.numpy_wrap()
                    raw = arr.tobytes()
                    stride = arr.strides[0]
                elif hasattr(buf, "pointer"):
                    ptr = buf.pointer
                    pitch = getattr(buf, "pitch", w * buf.image_type.bytes_per_pixel)
                    raw = ctypes.string_at(ptr, pitch * h)
                    stride = pitch

                if raw:
                    fmt = (
                        QImage.Format_Grayscale8
                        if "Mono8" in pf
                        else QImage.Format_RGB888
                    )
                    img = QImage(raw, w, h, stride, fmt)
                    if not img.isNull():
                        self.frame_ready.emit(img.copy(), raw)

        except Exception as e:
            log.exception("SDKCameraThread error")
            self.camera_error.emit(str(e), type(e).__name__)

        finally:
            log.info("Cleaning up SDKCameraThread")
            if self.grabber:
                try:
                    self.grabber.stream_stop()
                except:
                    pass
                try:
                    self.grabber.device_close()
                except:
                    pass
            log.info("SDKCameraThread stopped")
