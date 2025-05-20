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
            log.debug(f"Queued {min_buffers_required} buffers on sink")
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
        desired_pixel_format: str = "Y800",
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

        if not (
            self.pm and self.grabber and getattr(self.grabber, "is_device_open", False)
        ):
            return

        # ...rest of pending-properties code unchanged...

    def _emit_camera_properties(self):
        # ...unchanged...
        self.camera_properties_updated.emit({})

    def _emit_available_resolutions(self):
        # ...unchanged...
        self.camera_resolutions_available.emit([])

    def run(self):
        log.info(
            f"SDKCameraThread starting for {getattr(self.device_info, 'model_name', 'Unknown')}"
        )
        self.grabber = ic4.Grabber()
        try:
            if not self.device_info:
                devs = ic4.DeviceEnum.devices()
                if not devs:
                    raise RuntimeError("No cameras found")
                self.device_info = devs[0]

            # open device & property map
            self.grabber.device_open(self.device_info)
            self.pm = self.grabber.device_property_map
            log.info(f"Opened {self.device_info.model_name}")

            # ── initial setup: prefer desired PF (Y800) ──
            pfp = self.pm.find(PROP_PIXEL_FORMAT)
            if isinstance(pfp, PropEnumeration) and pfp.is_available:
                opts = [e.name for e in pfp.entries]
                # build candidate list prioritizing Y800
                candidates = [
                    self.desired_pixel_format_str,
                    "Y800",
                    "Mono8",
                    "Mono 8",
                ] + opts
                chosen_pf = None
                for c in candidates:
                    if c in opts:
                        chosen_pf = c
                        break
                if chosen_pf:
                    log.info(f"Setting PixelFormat → {chosen_pf}")
                    self._set_property_value(PROP_PIXEL_FORMAT, chosen_pf)
                    pf_clean = chosen_pf.replace(" ", "").lower()
                    if pf_clean in ("y800", "mono8"):
                        self.actual_qimage_format = QImage.Format_Grayscale8
                    else:
                        self.actual_qimage_format = QImage.Format_Grayscale8
                else:
                    log.warning("No supported PF found; defaulting to grayscale")
                    self.actual_qimage_format = QImage.Format_Grayscale8
            else:
                self.actual_qimage_format = QImage.Format_Grayscale8

            # set full-sensor ROI
            wp = self.pm.find(PROP_WIDTH)
            hp = self.pm.find(PROP_HEIGHT)
            if self._is_prop_writable(wp):
                log.info(f"Full-frame resolution: {wp.maximum}×{hp.maximum}")
                self._set_property_value(PROP_WIDTH, wp.maximum)
                self._set_property_value(PROP_HEIGHT, hp.maximum)
            self._set_property_value(PROP_OFFSET_X, 0)
            self._set_property_value(PROP_OFFSET_Y, 0)

            # continuous acquisition, trigger off
            self._set_property_value(PROP_ACQUISITION_MODE, "Continuous")
            self._set_property_value(PROP_TRIGGER_MODE, "Off")
            log.info("Configured continuous mode, trigger off")

            # queue & start streaming
            self.sink = ic4.QueueSink(self.dummy_listener)
            if hasattr(self.sink, "accept_incomplete_frames"):
                self.sink.accept_incomplete_frames = False
            log.info("QueueSink created and buffers queued")

            self.grabber.stream_setup(
                self.sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            log.info("Streaming started")

            # acquisition loop unchanged...
            while not self._stop_requested:
                # ...pop buffers, emit frames...
                break  # placeholder for brevity

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
