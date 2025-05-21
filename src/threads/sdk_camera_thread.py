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

        # override the readonly guard for our three controls:
        if getattr(prop, "is_readonly", True) and name not in (
            PROP_EXPOSURE_TIME,
            PROP_GAIN,
            PROP_EXPOSURE_AUTO,
        ):
            log.warning(f"Skipping truly read‐only prop {name}")
            return

        try:
            self.pm.set_value(name, val)
            log.info(f"Set {name} → {val}")
            self.camera_properties_updated.emit({name: val})
        except Exception as e:
            log.error(f"Failed to write {name}: {e}")

    def update_exposure(self, exposure_us: int):
        # ensure manual mode first
        self._set(PROP_EXPOSURE_AUTO, False)
        self._set(PROP_EXPOSURE_TIME, exposure_us)

    def update_gain(self, gain_db: float):
        # switch off auto‐exposure so gain writes are honored
        self._set(PROP_EXPOSURE_AUTO, False)
        self._set(PROP_GAIN, gain_db)

    def update_auto_exposure(self, enable_auto: bool):
        log.info(f"→ update_auto_exposure({enable_auto}) called")
        prop = self.pm.find(PROP_EXPOSURE_AUTO)
        if not prop or not prop.is_available:
            log.warning("Auto-exposure property not available")
            return

        # Many cameras expose this as an enum; look for common entry names
        entry_names = [e.name for e in getattr(prop, "entries", [])]
        if enable_auto:
            target = next((e for e in entry_names if "Continuous" in e), None)
        else:
            target = next((e for e in entry_names if "Off" in e), None)

        # fallback to boolean if the driver actually expects True/False
        val = target or enable_auto
        self._set(PROP_EXPOSURE_AUTO, val)

    def run(self):
        self._safe_init()
        self.grabber = ic4.Grabber()

        try:
            # 1) Open camera
            if not self.device_info:
                devs = ic4.DeviceEnum.devices()
                if not devs:
                    raise RuntimeError("No cameras found")
                self.device_info = devs[0]
            self.grabber.device_open(self.device_info)
            self.pm = self.grabber.device_property_map

            # --- enumerate exposure & gain caps for the UI ---
            controls = {}

            # ExposureTime
            exp_prop = self.pm.find(PROP_EXPOSURE_TIME)
            if exp_prop and exp_prop.is_available:
                exp_ctrl = {
                    "enabled": True,
                    "min": int(exp_prop.minimum),
                    "max": int(exp_prop.maximum),
                    "value": int(exp_prop.value),
                    "auto_available": False,
                    "is_auto_on": False,
                }
                auto_prop = self.pm.find(PROP_EXPOSURE_AUTO)
                if auto_prop and auto_prop.is_available:
                    exp_ctrl["auto_available"] = True
                    # map current auto value
                    auto_val = auto_prop.value
                    exp_ctrl["is_auto_on"] = (
                        auto_val == "Continuous"
                        if isinstance(auto_val, str)
                        else bool(auto_val)
                    )
                controls["exposure"] = exp_ctrl

            # Gain
            gain_prop = self.pm.find(PROP_GAIN)
            if gain_prop and gain_prop.is_available:
                controls["gain"] = {
                    "enabled": True,
                    "min": float(gain_prop.minimum),
                    "max": float(gain_prop.maximum),
                    "value": float(gain_prop.value),
                }

            # send full controls dict to the UI
            self.camera_properties_updated.emit({"controls": controls})

            # 2) (Optional) emit UI lists
            # -- you can populate resolutions/formats here if needed --

            # 3) Configure exactly what worked in test_ic4.py
            self._set(PROP_PIXEL_FORMAT, "Mono8")
            self._set(PROP_WIDTH, self.desired_width)
            self._set(PROP_HEIGHT, self.desired_height)

            fps_prop = self.pm.find(PROP_ACQUISITION_FRAME_RATE)
            if fps_prop and fps_prop.is_available:
                # clamp between min and max
                tgt = max(fps_prop.minimum, min(self.target_fps, fps_prop.maximum))
                self._set(PROP_ACQUISITION_FRAME_RATE, tgt)

            self._set(PROP_ACQUISITION_MODE, "Continuous")
            self._set(PROP_TRIGGER_MODE, "Off")

            # 4) Start streaming
            self.sink = ic4.VideoSink(self.listener)
            self.sink.timeout = 5000  # give the camera up to 5 s to start

            # a brief pause lets the camera apply settings
            time.sleep(0.05)

            self.grabber.stream_setup(
                self.sink,
                setup_option=ic4.StreamSetupOption.ACQUISITION_START,
            )
            log.info("Streaming started—entering acquisition loop")

            # 5) Acquisition loop
            while not self._stop:
                try:
                    buf = self.sink.pop_output_buffer()
                except ic4.IC4Exception:
                    time.sleep(0.05)
                    continue

                # build a QImage directly from the buffer
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
                    # emit the QImage directly
                    self.frame_ready.emit(img, data)

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
