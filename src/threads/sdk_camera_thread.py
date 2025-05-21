import logging
import time
import ctypes
import imagingcontrol4 as ic4

from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QImage

from imagingcontrol4.properties import PropEnumeration

log = logging.getLogger(__name__)

# GenICam property names
PROP_WIDTH = "Width"
PROP_HEIGHT = "Height"
PROP_PIXEL_FORMAT = "PixelFormat"
PROP_ACQUISITION_FRAME_RATE = "AcquisitionFrameRate"
PROP_ACQUISITION_MODE = "AcquisitionMode"
PROP_TRIGGER_MODE = "TriggerMode"
PROP_OFFSET_X = "OffsetX"
PROP_OFFSET_Y = "OffsetY"

# Supported (width, height, max FPS) from the TIS PDF manuals
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
        log.debug("Sink disconnected")


class SDKCameraThread(QThread):
    frame_ready = pyqtSignal(QImage, object)
    camera_resolutions_available = pyqtSignal(list)
    camera_video_formats_available = pyqtSignal(list)
    camera_properties_updated = pyqtSignal(dict)
    camera_error = pyqtSignal(str, str)

    def __init__(
        self,
        device_info=None,
        target_fps: float = 20.0,
        desired_width: int = None,
        desired_height: int = None,
        desired_pixel_format: str = "Mono8",
        parent=None,
    ):
        super().__init__(parent)

        # store these so the existing widget calls continue to work:
        self.device_info = device_info
        self.target_fps = target_fps
        self.desired_width = desired_width
        self.desired_height = desired_height
        self.desired_pixel_format_str = desired_pixel_format
        self.device_info = device_info
        self.target_fps = target_fps
        self._stop = False
        self.grabber = None
        self.sink = None
        self.pm = None
        self.qfmt = QImage.Format_Grayscale8
        self.listener = DummySinkListener()

    def request_stop(self):
        self._stop = True

    def _safe_init(self):
        try:
            ic4.Library.init()
        except RuntimeError:
            pass

    def _set(self, name, val):
        p = self.pm.find(name)
        if p and p.is_available and not getattr(p, "is_readonly", True):
            self.pm.set_value(name, val)
            log.info(f"Set {name} → {val}")

    def run(self):
        self._safe_init()
        self.grabber = ic4.Grabber()
        try:
            # Open the camera
            if not self.device_info:
                devs = ic4.DeviceEnum.devices()
                if not devs:
                    raise RuntimeError("No cameras found")
                self.device_info = devs[0]
            self.grabber.device_open(self.device_info)
            self.pm = self.grabber.device_property_map
            log.info(f"Opened {self.device_info.model_name}")

            # Choose PixelFormat = Mono8
            self._set(PROP_PIXEL_FORMAT, "Mono8")

            # Clamp FPS into the camera’s real limits
            fps_p = self.pm.find(PROP_ACQUISITION_FRAME_RATE)
            if fps_p and fps_p.is_available:
                mn, mx = fps_p.minimum, fps_p.maximum
                tgt = max(mn, min(self.target_fps, mx))
                self._set(PROP_ACQUISITION_FRAME_RATE, tgt)

            # Continuous streaming
            self._set(PROP_ACQUISITION_MODE, "Continuous")
            self._set(PROP_TRIGGER_MODE, "Off")

            # Attempt to start streaming
            self.sink = ic4.QueueSink(self.listener)
            self.sink.timeout = 200
            try:
                self.grabber.stream_setup(
                    self.sink,
                    setup_option=ic4.StreamSetupOption.ACQUISITION_START,
                )
            except ic4.IC4Exception as ex:
                log.warning(
                    f"Initial stream start failed: {ex}. Trying documented fallbacks…"
                )
                model = getattr(self.device_info, "model_name", "")
                # 1) Try documented resolution fallbacks
                for w, h, maxfps in MODEL_FORMAT_TABLES.get(model, []):
                    if maxfps >= self.target_fps:
                        log.warning(
                            f"{model}: fallback to {w}×{h} @ {self.target_fps} FPS"
                        )
                        # stop any partial stream before changing props
                        try:
                            if self.grabber.is_streaming:
                                self.grabber.stream_stop()
                                time.sleep(0.1)
                        except Exception:
                            pass
                        # apply fallback resolution
                        self._set(PROP_WIDTH, w)
                        self._set(PROP_HEIGHT, h)
                        # now restart streaming
                        self.grabber.stream_setup(
                            self.sink,
                            setup_option=ic4.StreamSetupOption.ACQUISITION_START,
                        )
                        break
                else:
                    # no matching resolution → clamp to minimum FPS and retry
                    fps_p = self.pm.find(PROP_ACQUISITION_FRAME_RATE)
                    if fps_p and fps_p.is_available:
                        log.warning(
                            "No matching resolution; clamping to min FPS and retrying"
                        )
                        # stop any partial stream first
                        try:
                            if self.grabber.is_streaming:
                                self.grabber.stream_stop()
                                time.sleep(0.1)
                        except Exception:
                            pass
                        # apply min-FPS
                        self._set(PROP_ACQUISITION_FRAME_RATE, fps_p.minimum)
                        # now restart acquisition
                        self.grabber.stream_setup(
                            self.sink,
                            setup_option=ic4.StreamSetupOption.ACQUISITION_START,
                        )

            else:
                # stop the live stream first
                if self.grabber.is_streaming:
                    self.grabber.stream_stop()
                    time.sleep(0.1)

                # apply the clamped FPS
                self._set(PROP_ACQUISITION_FRAME_RATE, fps_p.minimum)
                log.warning("Clamped to minimum FPS and retrying")
                # now restart acquisition
                self.grabber.stream_setup(
                    self.sink,
                    setup_option=ic4.StreamSetupOption.ACQUISITION_START,
                )

            log.info("Streaming started—entering acquisition loop")

            # Acquisition loop
            while not self._stop:
                try:
                    buf = self.sink.pop_output_buffer()
                except ic4.IC4Exception:
                    time.sleep(0.05)
                    continue

                if not buf or not buf.is_valid:
                    time.sleep(0.01)
                    continue

                w, h = buf.image_type.width, buf.image_type.height
                pf = buf.image_type.pixel_format.name
                data = None
                stride = w
                if hasattr(buf, "numpy_wrap"):
                    arr = buf.numpy_wrap()
                    data = arr.tobytes()
                    stride = arr.strides[0]
                elif hasattr(buf, "pointer"):
                    pitch = getattr(buf, "pitch", w * buf.image_type.bytes_per_pixel)
                    data = ctypes.string_at(buf.pointer, pitch * h)
                    stride = pitch

                if data:
                    fmt = (
                        QImage.Format_Grayscale8
                        if "Mono8" in pf
                        else QImage.Format_RGB888
                    )
                    img = QImage(data, w, h, stride, fmt)
                    if not img.isNull():
                        self.frame_ready.emit(img.copy(), data)

            log.info("Acquisition loop exited")

        except Exception as e:
            log.exception("Camera thread error")
            self.camera_error.emit(str(e), type(e).__name__)

        finally:
            log.info("Cleaning up camera thread")
            if self.grabber and getattr(self.grabber, "is_streaming", False):
                try:
                    self.grabber.stream_stop()
                except:
                    pass
            if self.grabber and getattr(self.grabber, "is_device_open", False):
                try:
                    self.grabber.device_close()
                except:
                    pass
            log.info("Camera thread stopped")
