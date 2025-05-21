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

    def __init__(
        self,
        device_info=None,
        target_fps: float = 20.0,
        desired_width: int = None,
        desired_height: int = None,
        parent=None,
    ):
        super().__init__(parent)
        self.device_info = device_info
        self.target_fps = target_fps
        self.desired_width = desired_width
        self.desired_height = desired_height
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

            # 2) Emit UI choices
            formats = MODEL_FORMAT_TABLES.get(model, [])
            self.camera_resolutions_available.emit([f"{w}×{h}" for w, h, _ in formats])
            self.camera_video_formats_available.emit([PROP_PIXEL_FORMAT])

            # 3) If the UI has asked for a specific WxH, try that first
            candidates = []
            if self.desired_width and self.desired_height:
                candidates.append((self.desired_width, self.desired_height))
            # then fall back to every supported resolution (small to large)
            candidates += [
                (w, h) for w, h, _ in sorted(formats, key=lambda t: t[0] * t[1])
            ]

            # 4) Configure common props once
            self._set(PROP_PIXEL_FORMAT, "Mono8")
            fps_prop = self.pm.find(PROP_ACQUISITION_FRAME_RATE)
            mn, mx = (None, None)
            if fps_prop and fps_prop.is_available:
                mn, mx = fps_prop.minimum, fps_prop.maximum

            self._set(PROP_ACQUISITION_MODE, "Continuous")
            self._set(PROP_TRIGGER_MODE, "Off")

            self.sink = ic4.QueueSink(self.listener)
            self.sink.timeout = 200

            # 5) Try each resolution until one works
            for w, h in candidates:
                log.info(f"Trying resolution {w}×{h} @ target {self.target_fps} FPS")
                # set it
                try:
                    self._set(PROP_WIDTH, w)
                    self._set(PROP_HEIGHT, h)
                    if mn is not None:
                        tgt = max(mn, min(self.target_fps, mx))
                        self._set(PROP_ACQUISITION_FRAME_RATE, tgt)
                    # give the camera a moment
                    time.sleep(0.05)
                    # attempt full‐acquisition start
                    self.grabber.stream_setup(
                        self.sink,
                        setup_option=ic4.StreamSetupOption.ACQUISITION_START,
                    )
                    log.info("  → success!")
                    break
                except Exception as e:
                    log.warning(f"  x failed at {w}×{h}: {e}")
                    # try minimum‐fps fallback on that resolution
                    if fps_prop and fps_prop.is_available:
                        try:
                            if self.grabber.is_streaming:
                                self.grabber.stream_stop()
                                time.sleep(0.05)
                            self._set(PROP_ACQUISITION_FRAME_RATE, fps_prop.minimum)
                            self.grabber.stream_setup(
                                self.sink,
                                setup_option=ic4.StreamSetupOption.ACQUISITION_START,
                            )
                            log.info("  → success @ min-FPS fallback!")
                            break
                        except Exception as e2:
                            log.warning(f"    also failed @ min-FPS: {e2}")
                    # nothing worked, move on to next resolution
            else:
                raise RuntimeError(
                    "Could not start streaming on any supported resolution"
                )

            log.info("Streaming started—entering acquisition loop")

            # 6) Acquisition loop
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
