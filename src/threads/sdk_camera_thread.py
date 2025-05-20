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
            # allocate and queue buffers so frames flow immediately
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
        desired_pixel_format: str = "Y800",
        parent=None,
    ):
        super().__init__(parent)
        self.device_info = device_info
        self.target_fps = target_fps
        self.desired_width = desired_width
        self.desired_height = desired_height
        # default to Y800 (2448×2048 on DMK33UP5000) for full-frame
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

            # ── pick pixel format (prefer Y800) ──
            pfp = self.pm.find(PROP_PIXEL_FORMAT)
            if isinstance(pfp, PropEnumeration) and pfp.is_available:
                opts = [e.name for e in pfp.entries]
                for candidate in ("Y800", "Mono8", "Mono 8", opts[0]):
                    if candidate in opts:
                        chosen_pf = candidate
                        break
                log.info(f"Setting PixelFormat → {chosen_pf}")
                self.pm.set_value(PROP_PIXEL_FORMAT, chosen_pf)

                clean = chosen_pf.replace(" ", "").lower()
                if clean.startswith(("y800", "mono8")):
                    self.actual_qimage_format = QImage.Format_Grayscale8
                elif clean.startswith(("rgb8", "bgr8")):
                    self.actual_qimage_format = QImage.Format_RGB888
                else:
                    log.warning(f"PF '{chosen_pf}' unrecognized, defaulting to gray8")
                    self.actual_qimage_format = QImage.Format_Grayscale8
            else:
                self.actual_qimage_format = QImage.Format_Grayscale8

            # ── set full-sensor ROI based on chosen PF ──
            wp = self.pm.find(PROP_WIDTH)
            hp = self.pm.find(PROP_HEIGHT)
            if wp and wp.is_available and not wp.is_readonly:
                self.pm.set_value(PROP_WIDTH, wp.maximum)
            if hp and hp.is_available and not hp.is_readonly:
                self.pm.set_value(PROP_HEIGHT, hp.maximum)
            # reset offsets to origin
            self.pm.set_value(PROP_OFFSET_X, 0)
            self.pm.set_value(PROP_OFFSET_Y, 0)
            log.info(f"Full-frame resolution: {wp.value}×{hp.value}")

            # continuous streaming
            self.pm.set_value(PROP_ACQUISITION_MODE, "Continuous")
            self.pm.set_value(PROP_TRIGGER_MODE, "Off")
            log.info("Configured continuous mode, trigger off")

            # start sink + stream
            self.sink = ic4.QueueSink(self.dummy_listener)
            if hasattr(self.sink, "accept_incomplete_frames"):
                self.sink.accept_incomplete_frames = False
            log.info("QueueSink created and buffers queued")

            self.grabber.stream_setup(
                self.sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            log.info("Streaming started")

            # grab loop
            last_emit = time.monotonic()
            frame_interval = 1.0 / self.target_fps
            while not self._stop_requested:
                try:
                    buf = self.sink.pop_output_buffer()
                except ic4.IC4Exception as ex:
                    if "NoData" in ex.code.name:
                        self.msleep(50)
                        continue
                    log.error("Stream error", exc_info=True)
                    break

                if buf is None:
                    self.msleep(50)
                    continue

                w, h = buf.image_type.width, buf.image_type.height
                raw = None
                if hasattr(buf, "numpy_wrap"):
                    arr = buf.numpy_wrap()
                    raw = arr.tobytes()
                    stride = arr.strides[0]
                elif hasattr(buf, "pointer"):
                    ptr = buf.pointer
                    pitch = getattr(buf, "pitch", w)
                    raw = ctypes.string_at(ptr, pitch * h)
                    stride = pitch
                else:
                    raw = buf.numpy_copy().tobytes()
                    stride = w

                img = QImage(raw, w, h, stride, self.actual_qimage_format)
                if not img.isNull() and time.monotonic() - last_emit >= frame_interval:
                    last_emit = time.monotonic()
                    self.frame_ready.emit(img.copy(), raw)

                buf.release()

            log.info("Exited capture loop")

        except Exception:
            log.exception("Camera run failed")
            self.camera_error.emit("Unexpected", "Exception")

        finally:
            log.info("Cleaning up camera")
            if getattr(self.grabber, "is_streaming", False):
                self.grabber.stream_stop()
            if getattr(self.grabber, "is_device_open", False):
                self.grabber.device_close()
            self.grabber = self.sink = self.pm = None
            log.info("SDKCameraThread stopped")
