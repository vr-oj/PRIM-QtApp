import logging
import time
import ctypes
import imagingcontrol4 as ic4

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)

# GenICam property names
PROP_WIDTH = "Width"
PROP_HEIGHT = "Height"
PROP_PIXEL_FORMAT = "PixelFormat"
PROP_ACQUISITION_FRAME_RATE = "AcquisitionFrameRate"
PROP_ACQUISITION_MODE = "AcquisitionMode"
PROP_TRIGGER_MODE = "TriggerMode"

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
    camera_resolutions_available = pyqtSignal(list)  # emits List[str]
    camera_video_formats_available = pyqtSignal(list)
    camera_properties_updated = pyqtSignal(dict)
    camera_error = pyqtSignal(str, str)

    def __init__(self, device_info=None, target_fps: float = 20.0, parent=None):
        super().__init__(parent)
        self.device_info = device_info
        self.target_fps = target_fps
        self._stop = False
        self.grabber = None
        self.sink = None
        self.pm = None
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
            self.camera_properties_updated.emit({name: val})

    def run(self):
        self._safe_init()
        self.grabber = ic4.Grabber()

        try:
            # 1) Open device
            if not self.device_info:
                devs = ic4.DeviceEnum.devices()
                if not devs:
                    raise RuntimeError("No cameras found")
                self.device_info = devs[0]
            self.grabber.device_open(self.device_info)
            self.pm = self.grabber.device_property_map
            model = getattr(self.device_info, "model_name", "")

            # pick the smallest supported resolution (last entry)
            try:
                w, h, _ = MODEL_FORMAT_TABLES[model][-1]
                log.info(f"Setting low resolution: {w}×{h}")
                self._set(PROP_WIDTH, w)
                self._set(PROP_HEIGHT, h)
            except (KeyError, IndexError):
                log.warning(
                    "No low‑res fallback defined for this model; using defaults"
                )

            # 2) Set pixel format, FPS, continuous & trigger
            self._set(PROP_PIXEL_FORMAT, "Mono8")
            fps_p = self.pm.find(PROP_ACQUISITION_FRAME_RATE)
            if fps_p and fps_p.is_available:
                mn, mx = fps_p.minimum, fps_p.maximum
                tgt = max(mn, min(self.target_fps, mx))
                self._set(PROP_ACQUISITION_FRAME_RATE, tgt)

            self._set(PROP_ACQUISITION_MODE, "Continuous")
            self._set(PROP_TRIGGER_MODE, "Off")

            # 3) Try streaming immediately
            self.sink = ic4.QueueSink(self.listener)
            self.sink.timeout = 200

            try:
                self.grabber.stream_setup(
                    self.sink,
                    setup_option=ic4.StreamSetupOption.ACQUISITION_START,
                )
            except ic4.IC4Exception as ex:
                log.warning(
                    f"Initial stream failed: {ex}; clamping to min FPS and retrying"
                )
                if fps_p and fps_p.is_available:
                    self.grabber.stream_stop()
                    time.sleep(0.1)
                    self._set(PROP_ACQUISITION_FRAME_RATE, fps_p.minimum)
                    self.grabber.stream_setup(
                        self.sink,
                        setup_option=ic4.StreamSetupOption.ACQUISITION_START,
                    )

            log.info("Streaming started—entering acquisition loop")

            # 4) Acquisition loop
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

                if hasattr(buf, "numpy_wrap"):
                    arr = buf.numpy_wrap()
                    data = arr.tobytes()
                    stride = arr.strides[0]
                else:
                    pitch = getattr(buf, "pitch", w * buf.image_type.bytes_per_pixel)
                    data = ctypes.string_at(buf.pointer, pitch * h)
                    stride = pitch

                fmt = (
                    QImage.Format_Grayscale8 if "Mono8" in pf else QImage.Format_RGB888
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
