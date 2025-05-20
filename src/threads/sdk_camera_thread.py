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
        # existing emission logic
        self.camera_properties_updated.emit(info)

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
            if not self.device_info:
                devs = ic4.DeviceEnum.devices()
                if not devs:
                    raise RuntimeError("No cameras found")
                self.device_info = devs[0]
            self.grabber.device_open(self.device_info)
            self.pm = self.grabber.device_property_map
            log.info(f"Opened {self.device_info.model_name}")
            # initial PF setup...
            # (omitted for brevity)
            # startup UI state
            self._apply_pending_properties()
            self._emit_available_resolutions()
            self._emit_camera_properties()

            self.sink = ic4.QueueSink(self.dummy_listener)
            if hasattr(self.sink, "accept_incomplete_frames"):
                self.sink.accept_incomplete_frames = False
            log.info("QueueSink created")

            self.grabber.stream_setup(
                self.sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            log.info("Streaming started")

            # 1) debug before loop
            log.debug(
                "About to enter acquisition loop; stop_requested=%s",
                self._stop_requested,
            )

            frame_count = 0
            no_data_count = 0
            last_emit = time.monotonic()
            frame_interval = 1.0 / self.target_fps

            while not self._stop_requested:
                # 2) log each iteration
                log.debug(
                    "Loop iteration start; stop_requested=%s", self._stop_requested
                )

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
                    log.error("Sink pop failed (will retry)", exc_info=True)
                    self.camera_error.emit(str(ex), name)
                    self.msleep(50)
                    continue
                if buf is None:
                    no_data_count += 1
                    if no_data_count % 200 == 0:
                        log.warning(f"pop returned None for ~{no_data_count*0.05:.1f}s")
                    self.msleep(50)
                    continue
                frame_count += 1
                no_data_count = 0
                w = buf.image_type.width
                h = buf.image_type.height
                log.debug(f"Frame {frame_count}: {w}×{h}")
                try:
                    # build QImage...
                    img = QImage(raw, w, h, stride, fmt)
                    if (
                        not img.isNull()
                        and time.monotonic() - last_emit >= frame_interval
                    ):
                        last_emit = time.monotonic()
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
