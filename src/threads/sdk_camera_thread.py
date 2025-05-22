# sdk_camera_thread.py
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
PROP_EXPOSURE_TIME = "ExposureTime"
PROP_EXPOSURE_AUTO = "ExposureAuto"
PROP_GAIN = "Gain"


class DummySinkListener:
    # Required by SnapSink: how many buffers to allocate and require on connect
    num_buffers_alloc_on_connect = 6  # For snapsink.py line 98
    num_buffers_allocation_threshold = 6  # For snapsink.py line 99
    num_buffers_required_on_connect = 6

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
        desired_width: int = 2448,
        desired_height: int = 2048,
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
        prop = self.pm.find(name)
        if not prop or not prop.is_available:
            log.warning(f"Cannot set {name}: property not available")
            return
        if getattr(prop, "is_readonly", True) and name not in (
            PROP_EXPOSURE_TIME,
            PROP_GAIN,
            PROP_EXPOSURE_AUTO,
        ):
            log.warning(f"Skipping read-only property {name}")
            return
        try:
            self.pm.set_value(name, val)
            log.info(f"Set {name} → {val}")
            self.camera_properties_updated.emit({name: val})
        except Exception as e:
            log.error(f"Failed to set {name}: {e}")

    def update_exposure(self, exposure_us: int):
        self._set(PROP_EXPOSURE_AUTO, False)
        self._set(PROP_EXPOSURE_TIME, exposure_us)

    def update_gain(self, gain_db: float):
        self._set(PROP_EXPOSURE_AUTO, False)
        self._set(PROP_GAIN, gain_db)

    def update_auto_exposure(self, enable_auto: bool):
        prop = self.pm.find(PROP_EXPOSURE_AUTO)
        if not prop or not prop.is_available:
            log.warning("Auto-exposure not available")
            return
        entries = [e.name for e in getattr(prop, "entries", [])]
        if enable_auto:
            target = next((n for n in entries if "Continuous" in n), None)
        else:
            target = next((n for n in entries if "Off" in n), None)
        self._set(PROP_EXPOSURE_AUTO, target or enable_auto)

    def run(self):
        self._safe_init()
        self.grabber = ic4.Grabber()
        # extend grabber-level timeout for AcquisitionStart
        try:
            self.grabber.set_timeout(10000)
        except AttributeError:
            self.grabber.timeout = 10000

        try:
            # Open device
            if not self.device_info:
                devices = ic4.DeviceEnum.devices()
                if not devices:
                    raise RuntimeError("No cameras found")
                self.device_info = devices[0]
            self.grabber.device_open(self.device_info)
            self.pm = self.grabber.device_property_map

            # Stream buffer negotiation and start
            # Use native SnapSink callback model
            self.sink = ic4.SnapSink(self.listener)
            self.grabber.stream_setup(self.sink)
            self.grabber.acquisition_start()
            log.info("Streaming started via SnapSink + acquisition_start")

            # Acquisition loop
            while not self._stop:
                try:
                    buf = self.sink.pop_output_buffer()
                except ic4.IC4Exception:
                    time.sleep(0.01)
                    continue
                w, h = buf.image_type.width, buf.image_type.height
                pf = buf.image_type.pixel_format.name
                # extract bytes
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
                    self.frame_ready.emit(img, data)

        except Exception as e:
            log.exception("Camera thread error")
            self.camera_error.emit(str(e), type(e).__name__)

        finally:
            # cleanup
            if self.grabber:
                try:
                    if self.grabber.is_streaming:
                        self.grabber.stream_stop()
                except Exception:
                    pass
                try:
                    if self.grabber.is_device_open:
                        self.grabber.device_close()
                except Exception:
                    pass
            log.info("Camera thread stopped")
