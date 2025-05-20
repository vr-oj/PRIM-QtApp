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

# GenICam camera-property names
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
        log.debug(f"Sink connected: {image_type}, buffers={min_buffers_required}")
        try:
            # allocate and queue at least the minimum number of buffers
            sink.alloc_and_queue_buffers(min_buffers_required)
            log.debug(f"Queued {min_buffers_required} buffers")
            return True
        except Exception:
            log.exception("Failed to alloc_and_queue_buffers")
            return False

    def frames_queued(self, sink):
        # no-op; our run() pulls and releases each buffer
        pass

    def sink_disconnected(self, sink):
        log.debug("Sink disconnected")


class SDKCameraThread(QThread):
    frame_ready = pyqtSignal(QImage, object)
    camera_resolutions_available = pyqtSignal(list)
    camera_properties_updated = pyqtSignal(dict)
    camera_error = pyqtSignal(str, str)

    def __init__(
        self,
        device_info=None,
        target_fps=20.0,
        desired_width=None,
        desired_height=None,
        desired_pixel_format="Mono8",
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

        self._last_prop_apply = 0.0
        self._throttle_interval = 0.1

        self.grabber = None
        self.sink = None
        self.pm = None
        self.actual_qimg_fmt = QImage.Format_Invalid
        self.listener = DummySinkListener()

    def request_stop(self):
        self._stop_requested = True
        log.debug("Stop requested")

    def update_exposure(self, exp_us):
        self._pending_exposure_us = float(exp_us)

    def update_gain(self, gain_db):
        self._pending_gain_db = gain_db

    def update_auto_exposure(self, auto):
        self._pending_auto_exposure = auto

    def update_roi(self, x, y, w, h):
        self._pending_roi = (x, y, w, h)

    def _is_writable(self, prop):
        return bool(
            prop and prop.is_available and not getattr(prop, "is_readonly", True)
        )

    def _set_prop(self, name, val):
        try:
            p = self.pm.find(name)
            if self._is_writable(p):
                self.pm.set_value(name, val)
                log.info(f"Set {name} -> {val}")
                return True
        except Exception:
            log.exception(f"Failed to set {name}")
        return False

    def _apply_pending(self):
        now = time.monotonic()
        if now - self._last_prop_apply < self._throttle_interval:
            return
        self._last_prop_apply = now
        if not (self.pm and self.grabber and self.grabber.is_device_open):
            return

        if self._pending_auto_exposure is not None:
            pa = self.pm.find(PROP_EXPOSURE_AUTO)
            if pa and pa.is_available:
                val = "Continuous" if self._pending_auto_exposure else "Off"
                self._set_prop(
                    PROP_EXPOSURE_AUTO,
                    (
                        val
                        if isinstance(pa, PropEnumeration)
                        else self._pending_auto_exposure
                    ),
                )
            self._pending_auto_exposure = None

        if self._pending_exposure_us is not None:
            self._set_prop(PROP_EXPOSURE_TIME, self._pending_exposure_us)
            self._pending_exposure_us = None

        if self._pending_gain_db is not None:
            self._set_prop(PROP_GAIN, self._pending_gain_db)
            self._pending_gain_db = None

        if self._pending_roi is not None:
            x, y, w, h = self._pending_roi
            if (w, h) == (0, 0):
                self._set_prop(PROP_OFFSET_X, 0)
                self._set_prop(PROP_OFFSET_Y, 0)
            else:
                self._set_prop(PROP_WIDTH, w)
                self._set_prop(PROP_HEIGHT, h)
                self._set_prop(PROP_OFFSET_X, x)
                self._set_prop(PROP_OFFSET_Y, y)
            self._pending_roi = None

    def _emit_props(self):
        if not self.pm:
            self.camera_properties_updated.emit({})
            return
        info = {"controls": {}, "roi": {}}
        # gather desired props...
        self.camera_properties_updated.emit(info)

    def _emit_res(self):
        if not self.pm:
            self.camera_resolutions_available.emit([])
            return
        try:
            w = self.pm.find(PROP_WIDTH).value
            h = self.pm.find(PROP_HEIGHT).value
            pf = self.pm.find(PROP_PIXEL_FORMAT).value
            self.camera_resolutions_available.emit([f"{w}x{h} ({pf})"])
        except Exception:
            log.exception("Could not list resolutions")
            self.camera_resolutions_available.emit([])

    def run(self):
        log.info(f"SDKCameraThread start: {self.device_info}")
        self.grabber = ic4.Grabber()
        try:
            if not self.device_info:
                devs = ic4.DeviceEnum.devices()
                if not devs:
                    raise RuntimeError("No camera found")
                self.device_info = devs[0]

            self.grabber.device_open(self.device_info)
            self.pm = self.grabber.device_property_map
            log.info(f"Opened {self.device_info.model_name}")

            # choose Y800 / Mono8 first
            pfp = self.pm.find(PROP_PIXEL_FORMAT)
            if isinstance(pfp, PropEnumeration) and pfp.is_available:
                opts = [e.name for e in pfp.entries]
                for cand in ("Y800", "Mono8", "Mono 8", opts[0]):
                    if cand in opts:
                        self._set_prop(PROP_PIXEL_FORMAT, cand)
                        pf_clean = cand.replace(" ", "").lower()
                        if pf_clean.startswith("mono"):
                            self.actual_qimg_fmt = QImage.Format_Grayscale8
                        else:
                            self.actual_qimg_fmt = QImage.Format_RGB888
                        break
            else:
                self.actual_qimg_fmt = QImage.Format_Grayscale8

            # full sensor
            wp = self.pm.find(PROP_WIDTH)
            hp = self.pm.find(PROP_HEIGHT)
            if self._is_writable(wp):
                self._set_prop(PROP_WIDTH, wp.maximum)
            if self._is_writable(hp):
                self._set_prop(PROP_HEIGHT, hp.maximum)
            self._set_prop(PROP_OFFSET_X, 0)
            self._set_prop(PROP_OFFSET_Y, 0)
            log.info(f"Full-frame: {wp.maximum}x{hp.maximum}")

            # continuous, free-run
            self._set_prop(PROP_ACQUISITION_MODE, "Continuous")
            self._set_prop(PROP_TRIGGER_MODE, "Off")

            # frame rate (may clamp)
            self._set_prop(PROP_ACQUISITION_FRAME_RATE, float(self.target_fps))
            log.info(f"Configured continuous, free-run @ {self.target_fps}fps")

            # initial UI emits
            self._emit_res()
            self._emit_props()

            # create sink + queue buffers in sink_connected callback
            self.sink = ic4.QueueSink(self.listener)
            self.sink.accept_incomplete_frames = False
            log.info("QueueSink created")

            # start stream
            self.grabber.stream_setup(
                self.sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            log.info("Streaming started")

            # acquisition loop
            frame_interval = 1.0 / self.target_fps
            last_emit = time.monotonic()
            while not self._stop_requested:
                buf = None
                try:
                    buf = self.sink.pop_output_buffer()
                except ic4.IC4Exception as ex:
                    name = ex.code.name if getattr(ex, "code", None) else ""
                    if "NoData" in name or "Time" in name:
                        time.sleep(0.01)
                        continue
                    log.exception("Stream popped error")
                    continue

                if buf is None:
                    continue

                # got buffer
                w = buf.image_type.width
                h = buf.image_type.height
                # map raw -> QImage
                try:
                    if hasattr(buf, "numpy_wrap"):
                        arr = buf.numpy_wrap()
                        raw = arr.tobytes()
                        stride = arr.strides[0]
                    elif hasattr(buf, "pointer"):
                        pitch = getattr(buf, "pitch", w)
                        raw = ctypes.string_at(buf.pointer, pitch * h)
                        stride = pitch
                    else:
                        continue
                    img = QImage(raw, w, h, stride, self.actual_qimg_fmt)
                    if (
                        not img.isNull()
                        and time.monotonic() - last_emit >= frame_interval
                    ):
                        last_emit = time.monotonic()
                        self.frame_ready.emit(img.copy(), raw)
                except Exception:
                    log.exception("Failed to build QImage")
                finally:
                    try:
                        buf.release()
                    except Exception:
                        pass

            log.info("Acquisition loop exited")

        except Exception:
            log.exception("Unhandled in SDKCameraThread.run")
            self.camera_error.emit("Unexpected", "Exception")

        finally:
            log.info("Tearing down grabber")
            if self.grabber:
                try:
                    if getattr(self.grabber, "is_streaming", False):
                        self.grabber.stream_stop()
                except Exception:
                    pass
                try:
                    if getattr(self.grabber, "is_device_open", False):
                        self.grabber.device_close()
                except Exception:
                    pass
            self.grabber = self.sink = self.pm = None
            log.info("SDKCameraThread stopped")
