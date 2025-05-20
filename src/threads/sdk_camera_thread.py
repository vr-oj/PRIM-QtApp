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
        try:
            # allocate and queue buffers on connect
            sink.alloc_and_queue_buffers(min_buffers_required)
            return True
        except Exception as e:
            log.error(f"Failed to queue buffers: {e}", exc_info=True)
            return False

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
        log.debug("SDKCameraThread: Stop requested")

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

        # (existing property application logic)
        # ...

    def _emit_camera_properties(self):
        if not self.pm:
            self.camera_properties_updated.emit({})
            return
        info = {"controls": {}, "roi": {}}
        # (existing property gathering)
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

            # ── initial setup ──
            pfp = self.pm.find(PROP_PIXEL_FORMAT)
            if isinstance(pfp, PropEnumeration) and pfp.is_available:
                opts = [e.name for e in pfp.entries]
                chosen_pf = next(
                    (c for c in ("Mono8", "Mono 8", opts[0]) if c in opts), opts[0]
                )
                self._set_property_value(PROP_PIXEL_FORMAT, chosen_pf)
                pf_clean = chosen_pf.replace(" ", "").lower()
                self.actual_qimage_format = (
                    QImage.Format_Grayscale8
                    if pf_clean.startswith("mono8")
                    else QImage.Format_RGB888
                )
            else:
                self.actual_qimage_format = QImage.Format_Grayscale8

            wp = self.pm.find(PROP_WIDTH)
            hp = self.pm.find(PROP_HEIGHT)
            # full sensor
            if self._is_prop_writable(wp):
                self._set_property_value(PROP_WIDTH, wp.maximum)
            if self._is_prop_writable(hp):
                self._set_property_value(PROP_HEIGHT, hp.maximum)
            self._set_property_value(PROP_OFFSET_X, 0)
            self._set_property_value(PROP_OFFSET_Y, 0)
            log.info(f"Full-sensor: {wp.value}×{hp.value}")

            # small ROI for troubleshooting
            max_w, max_h = wp.maximum, hp.maximum
            test_w, test_h = min(640, max_w), min(480, max_h)
            self._set_property_value(PROP_WIDTH, test_w)
            self._set_property_value(PROP_HEIGHT, test_h)
            self._set_property_value(PROP_OFFSET_X, (max_w - test_w) // 2)
            self._set_property_value(PROP_OFFSET_Y, (max_h - test_h) // 2)
            log.info(f"Testing small ROI: {test_w}×{test_h}")

            # continuous, trigger off
            self._set_property_value(PROP_ACQUISITION_MODE, "Continuous")
            self._set_property_value(PROP_TRIGGER_MODE, "Off")
            # clamp FPS
            afr = self.pm.find(PROP_ACQUISITION_FRAME_RATE)
            if isinstance(afr, (PropInteger, PropFloat)) and afr.is_available:
                low, high = afr.minimum, afr.maximum
                fps = max(min(self.target_fps, high), low)
                self._set_property_value(PROP_ACQUISITION_FRAME_RATE, float(fps))
                log.info(f"Clamped frame rate: {fps}")
            else:
                self._set_property_value(
                    PROP_ACQUISITION_FRAME_RATE, float(self.target_fps)
                )

            # UI state
            self._apply_pending_properties()
            self._emit_available_resolutions()
            self._emit_camera_properties()

            # start streaming
            self.sink = ic4.QueueSink(self.dummy_listener)
            if hasattr(self.sink, "accept_incomplete_frames"):
                self.sink.accept_incomplete_frames = False
            log.info("QueueSink created")
            self.grabber.stream_setup(
                self.sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            log.info("Streaming started")

            frame_interval = 1.0 / self.target_fps
            last_emit = time.monotonic()
            while not self._stop_requested:
                self._apply_pending_properties()
                try:
                    buf = self.sink.pop_output_buffer()
                except ic4.IC4Exception as ex:
                    name = getattr(ex.code, "name", "")
                    if "NoData" in name or "Time" in name:
                        self.msleep(50)
                        continue
                    self.camera_error.emit(str(ex), name)
                    self.msleep(50)
                    continue
                if buf is None:
                    self.msleep(50)
                    continue

                w, h = buf.image_type.width, buf.image_type.height
                try:
                    if hasattr(buf, "numpy_wrap"):
                        arr = buf.numpy_wrap()
                        raw = arr.tobytes()
                        stride = arr.strides[0]
                    elif hasattr(buf, "numpy_copy"):
                        arr = buf.numpy_copy()
                        raw = arr.tobytes()
                        stride = arr.strides[0]
                    elif hasattr(buf, "pointer"):
                        pitch = getattr(buf, "pitch", w)
                        raw = ctypes.string_at(buf.pointer, pitch * h)
                        stride = pitch
                    else:
                        raise RuntimeError
                    img = QImage(raw, w, h, stride, self.actual_qimage_format)
                    now = time.monotonic()
                    if not img.isNull() and now - last_emit >= frame_interval:
                        last_emit = now
                        self.frame_ready.emit(img.copy(), raw)
                except Exception:
                    log.error("QImage failed", exc_info=True)
                finally:
                    try:
                        buf.release()
                    except:
                        pass

        except Exception:
            log.exception("Unhandled in run()")
            self.camera_error.emit("Unexpected", "Exception")
        finally:
            log.info("Shutting down grabber")
            if self.grabber:
                try:
                    self.grabber.stream_stop()
                except:
                    pass
                try:
                    self.grabber.device_close()
                except:
                    pass
            self.grabber = self.sink = self.pm = None
            log.info("SDKCameraThread fully stopped")
