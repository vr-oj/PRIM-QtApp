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
    # signals
    frame_ready = pyqtSignal(QImage, object)
    camera_resolutions_available = pyqtSignal(list)  # ["640x480", ...]
    camera_video_formats_available = pyqtSignal(
        list
    )  # [{"id":"Mono8","text":"Mono8"}, ...]
    camera_properties_updated = pyqtSignal(dict)
    camera_error = pyqtSignal(str, str)

    def __init__(
        self,
        device_info: "ic4.DeviceInfo" = None,
        target_fps: float = 20.0,
        parent=None,
    ):
        super().__init__(parent)
        self.device_info = device_info
        self.target_fps = target_fps
        self._stop_requested = False
        self._pending_roi = None
        self._pending_exposure_us = None
        self._pending_gain_db = None
        self._pending_auto_exposure = None
        self._last_prop_apply_time = 0.0
        self._prop_throttle_interval = 0.1
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

    @pyqtSlot(tuple)
    def update_roi(self, rect):
        self._pending_roi = rect  # (x,y,w,h)

    @pyqtSlot(str)
    def select_resolution(self, res_str: str):
        """Called by UI when user picks e.g. '1280x720'."""
        w, h = map(int, res_str.split("x"))
        self.pm.set_value(PROP_WIDTH, w)
        self.pm.set_value(PROP_HEIGHT, h)

    @pyqtSlot(str)
    def select_pixel_format(self, pf_name: str):
        """Called by UI when user picks a PixelFormat entry."""
        p = self.pm.find(PROP_PIXEL_FORMAT)
        if isinstance(p, PropEnumeration):
            self.pm.set_value(PROP_PIXEL_FORMAT, pf_name)
            log.info(f"PixelFormat set to {pf_name}")
        else:
            log.warning("PixelFormat property not enumeration!")

    def _is_writable(self, p):
        return bool(p and p.is_available and not getattr(p, "is_readonly", True))

    def _apply_pending_properties(self):
        now = time.monotonic()
        if now - self._last_prop_apply_time < self._prop_throttle_interval:
            return
        self._last_prop_apply_time = now

        if not (self.pm and self.grabber and self.grabber.is_device_open):
            return

        # ROI
        if self._pending_roi is not None:
            x, y, w, h = self._pending_roi
            self.pm.set_value(PROP_OFFSET_X, x)
            self.pm.set_value(PROP_OFFSET_Y, y)
            self._pending_roi = None

        # Exposure / gain / auto
        if self._pending_auto_exposure is not None:
            val = "Continuous" if self._pending_auto_exposure else "Off"
            if self._is_writable(self.pm.find(PROP_EXPOSURE_AUTO)):
                self.pm.set_value(PROP_EXPOSURE_AUTO, val)
            self._pending_auto_exposure = None

        if self._pending_exposure_us is not None:
            if not self.pm.find(PROP_EXPOSURE_AUTO).value == "Continuous":
                self.pm.set_value(PROP_EXPOSURE_TIME, self._pending_exposure_us)
            self._pending_exposure_us = None

        if self._pending_gain_db is not None:
            self.pm.set_value(PROP_GAIN, self._pending_gain_db)
            self._pending_gain_db = None

    def _emit_camera_properties(self):
        info = {"controls": {}, "roi": {}}
        # Build controls for exposure/gain as before…
        # (copy your old implementation here)
        self.camera_properties_updated.emit(info)

    def _emit_resolutions(self):
        # read Width/Height current and emit single-element list
        w = self.pm.find(PROP_WIDTH).value
        h = self.pm.find(PROP_HEIGHT).value
        self.camera_resolutions_available.emit([f"{w}x{h}"])

    def _emit_pixel_formats(self):
        p = self.pm.find(PROP_PIXEL_FORMAT)
        opts = []
        if isinstance(p, PropEnumeration) and p.is_available:
            for e in p.entries:
                opts.append({"id": e.name, "text": e.name})
        self.camera_video_formats_available.emit(opts)

    def run(self):
        log.info("SDKCameraThread starting")
        ic4.Library.init()  # ensure library initialized
        self.grabber = ic4.Grabber()
        try:
            # open device
            if not self.device_info:
                devs = ic4.DeviceEnum.devices()
                if not devs:
                    raise RuntimeError("No cameras found")
                self.device_info = devs[0]
            self.grabber.device_open(self.device_info)
            self.pm = self.grabber.device_property_map
            log.info(f"Opened {self.device_info.model_name}")

            # Populate UI dropdowns
            self._emit_pixel_formats()
            self._emit_resolutions()

            # Simplified setup: clamp FPS & set continuous/acquisition
            fps_p = self.pm.find(PROP_ACQUISITION_FRAME_RATE)
            if fps_p and fps_p.is_available:
                min_f, max_f = fps_p.minimum, fps_p.maximum
                tgt = min(max(self.target_fps, min_f), max_f)
                if self._is_writable(fps_p):
                    self.pm.set_value(PROP_ACQUISITION_FRAME_RATE, tgt)
                log.info(f"FPS set to {tgt}")
            self.pm.set_value(PROP_ACQUISITION_MODE, "Continuous")
            self.pm.set_value(PROP_TRIGGER_MODE, "Off")

            # push to UI
            self._emit_camera_properties()

            # start streaming
            self.sink = ic4.QueueSink(self.dummy_listener)
            self.sink.timeout = 200
            self.grabber.stream_setup(
                self.sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            log.info("Streaming started")

            fcount = 0
            nodata = 0
            while not self._stop_requested:
                self._apply_pending_properties()

                try:
                    buf = self.sink.pop_output_buffer()
                except ic4.IC4Exception as ex:
                    # handle Timeout/NoData
                    nodata += 1
                    self.msleep(50)
                    continue

                if not buf or not buf.is_valid:
                    self.msleep(50)
                    continue

                # valid frame
                fcount += 1
                nodata = 0
                w = buf.image_type.width
                h = buf.image_type.height
                pf = buf.image_type.pixel_format.name
                log.info(f"Frame {fcount}: {w}×{h}, {pf}")

                # build QImage
                raw = None
                stride = w
                if hasattr(buf, "numpy_wrap"):
                    arr = buf.numpy_wrap()
                    stride = arr.strides[0]
                    raw = arr.tobytes()
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

            log.info("Acquisition loop ended")

        except Exception as ex:
            log.exception("Error in SDKCameraThread")
            self.camera_error.emit(str(ex), type(ex).__name__)

        finally:
            log.info("Cleaning up")
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
