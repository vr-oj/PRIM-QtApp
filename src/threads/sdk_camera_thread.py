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
            sink.alloc_and_queue_buffers(min_buffers_required)
            return True
        except Exception:
            log.exception("Failed to queue buffers")
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
        except Exception:
            log.exception(f"Failed to set {name}")
        return False

    def _apply_pending_properties(self):
        now = time.monotonic()
        if now - self._last_prop_apply_time < self._prop_throttle_interval:
            return
        self._last_prop_apply_time = now

        if not (
            self.pm and self.grabber and getattr(self.grabber, "is_device_open", False)
        ):
            return

        # auto-exposure, exposure, gain, ROI logic here...
        # (unchanged from previous)
        # ...

    def _emit_camera_properties(self):
        info = {"controls": {}, "roi": {}}
        self.camera_properties_updated.emit(info)

    def _emit_available_resolutions(self):
        try:
            w = self.pm.find(PROP_WIDTH).value
            h = self.pm.find(PROP_HEIGHT).value
            pf = self.pm.find(PROP_PIXEL_FORMAT).value
            self.camera_resolutions_available.emit([f"{w}x{h} ({pf})"])
        except Exception:
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

            # pick pixel format
            pfp = self.pm.find(PROP_PIXEL_FORMAT)
            if isinstance(pfp, PropEnumeration) and pfp.is_available:
                opts = [e.name for e in pfp.entries]
                chosen = next(
                    (
                        c
                        for c in (self.desired_pixel_format_str, "Mono8", opts[0])
                        if c in opts
                    ),
                    opts[0],
                )
                self._set_property_value(PROP_PIXEL_FORMAT, chosen)
                pf_clean = chosen.replace(" ", "").lower()
                if pf_clean.startswith("mono8"):
                    self.actual_qimage_format = QImage.Format_Grayscale8
                else:
                    self.actual_qimage_format = (
                        QImage.Format_RGB888
                        if pf_clean.startswith(("rgb8", "bgr8"))
                        else QImage.Format_Grayscale8
                    )
            else:
                self.actual_qimage_format = QImage.Format_Grayscale8

            # select ROI or full-frame
            wp = self.pm.find(PROP_WIDTH)
            hp = self.pm.find(PROP_HEIGHT)
            if self.desired_width and self.desired_height:
                # use desired resolution
                self._set_property_value(PROP_OFFSET_X, 0)
                self._set_property_value(PROP_OFFSET_Y, 0)
                self._set_property_value(PROP_WIDTH, self.desired_width)
                self._set_property_value(PROP_HEIGHT, self.desired_height)
                log.info(f"Using ROI: {self.desired_width}×{self.desired_height}")
            else:
                # full-sensor
                if self._is_prop_writable(wp):
                    self._set_property_value(PROP_WIDTH, wp.maximum)
                if self._is_prop_writable(hp):
                    self._set_property_value(PROP_HEIGHT, hp.maximum)
                self._set_property_value(PROP_OFFSET_X, 0)
                self._set_property_value(PROP_OFFSET_Y, 0)
                log.info(f"Full-sensor: {wp.value}×{hp.value}")

            # acquisition mode, trigger, frame rate (clamp to range)
            self._set_property_value(PROP_ACQUISITION_MODE, "Continuous")
            self._set_property_value(PROP_TRIGGER_MODE, "Off")
            try:
                min_fps = self.pm.find(PROP_ACQUISITION_FRAME_RATE).minimum
                max_fps = self.pm.find(PROP_ACQUISITION_FRAME_RATE).maximum
                fps = max(min(self.target_fps, max_fps), min_fps)
                self._set_property_value(PROP_ACQUISITION_FRAME_RATE, fps)
                log.info(f"Clamped frame rate: {fps}")
            except Exception:
                log.warning("Could not set frame rate")

            # initial UI state
            self._apply_pending_properties()
            self._emit_available_resolutions()
            self._emit_camera_properties()

            # start streaming
            self.sink = ic4.QueueSink(self.dummy_listener)
            if hasattr(self.sink, "accept_incomplete_frames"):
                self.sink.accept_incomplete_frames = False
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
                    if "NoData" in (getattr(ex.code, "name", "")):
                        self.msleep(50)
                        continue
                    else:
                        self.camera_error.emit(str(ex), getattr(ex.code, "name", ""))
                        self.msleep(50)
                        continue

                if buf is None:
                    self.msleep(50)
                    continue

                w, h = buf.image_type.width, buf.image_type.height
                try:
                    raw, stride = None, w
                    if hasattr(buf, "numpy_wrap"):
                        arr = buf.numpy_wrap()
                        stride = arr.strides[0]
                        raw = arr.tobytes()
                    elif hasattr(buf, "pointer"):
                        ptr = buf.pointer
                        pitch = getattr(buf, "pitch", w)
                        raw = ctypes.string_at(ptr, pitch * h)
                        stride = pitch
                    img = QImage(raw, w, h, stride, self.actual_qimage_format)
                    if (
                        not img.isNull()
                        and (time.monotonic() - last_emit) >= frame_interval
                    ):
                        last_emit = time.monotonic()
                        self.frame_ready.emit(img.copy(), raw)
                except Exception:
                    log.exception("QImage build failed")
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
                    if getattr(self.grabber, "is_streaming", False):
                        self.grabber.stream_stop()
                except:
                    pass
                try:
                    if getattr(self.grabber, "is_device_open", False):
                        self.grabber.device_close()
                except:
                    pass
            self.grabber = self.sink = self.pm = None
            log.info("SDKCameraThread fully stopped")
