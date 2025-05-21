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
            log.warning(f"Skipping truly read-only prop {name}")
            return
        try:
            self.pm.set_value(name, val)
            log.info(f"Set {name} → {val}")
            self.camera_properties_updated.emit({name: val})
        except Exception as e:
            log.error(f"Failed to write {name}: {e}")

    def update_exposure(self, exposure_us: int):
        self._set(PROP_EXPOSURE_AUTO, False)
        self._set(PROP_EXPOSURE_TIME, exposure_us)

    def update_gain(self, gain_db: float):
        self._set(PROP_EXPOSURE_AUTO, False)
        self._set(PROP_GAIN, gain_db)

    def update_auto_exposure(self, enable_auto: bool):
        log.info(f"→ update_auto_exposure({enable_auto}) called")
        prop = self.pm.find(PROP_EXPOSURE_AUTO)
        if not prop or not prop.is_available:
            log.warning("Auto-exposure property not available")
            return
        entry_names = [e.name for e in getattr(prop, "entries", [])]
        target = (
            next((e for e in entry_names if "Continuous" in e), None)
            if enable_auto
            else next((e for e in entry_names if "Off" in e), None)
        )
        self._set(PROP_EXPOSURE_AUTO, target or enable_auto)

    def run(self):
        self._safe_init()
        self.grabber = ic4.Grabber()
        # Give grabber extended timeout for AcquisitionStart
        try:
            self.grabber.set_timeout(10000)
        except AttributeError:
            self.grabber.timeout = 10000

        try:
            # 1) Open camera
            if not self.device_info:
                devs = ic4.DeviceEnum.devices()
                if not devs:
                    raise RuntimeError("No cameras found")
                self.device_info = devs[0]
            self.grabber.device_open(self.device_info)
            self.pm = self.grabber.device_property_map

            # 2) Dump all available GenICam properties for inspection
            #    including both device and driver property maps for USB3Vision features
            log.info("=== Device PropertyMap dump ===")
            if self.pm and hasattr(self.pm, "to_dict"):
                for pname in self.pm.to_dict().keys():
                    prop = self.pm.find(pname)
                    if prop and prop.is_available:
                        info = {
                            "value": prop.value,
                            "min": getattr(prop, "minimum", None),
                            "max": getattr(prop, "maximum", None),
                            "access": (
                                "RW" if not getattr(prop, "is_readonly", True) else "RO"
                            ),
                            "type": type(prop.value).__name__,
                        }
                        log.info(f"  {pname}: {info}")
            else:
                log.warning("Device PropertyMap has no to_dict(); cannot dump features")
            log.info("=== End Device PropertyMap dump ===")

            # Also check the driver-level PropertyMap for more low-level features
            try:
                dpm = self.grabber.driver_property_map
                log.info("=== Driver PropertyMap dump ===")
                if hasattr(dpm, "to_dict"):
                    for pname in dpm.to_dict().keys():
                        prop = dpm.find(pname)
                        if prop and prop.is_available:
                            info = {
                                "value": prop.value,
                                "min": getattr(prop, "minimum", None),
                                "max": getattr(prop, "maximum", None),
                                "access": (
                                    "RW"
                                    if not getattr(prop, "is_readonly", True)
                                    else "RO"
                                ),
                                "type": type(prop.value).__name__,
                            }
                            log.info(f"  {pname}: {info}")
                else:
                    log.warning(
                        "Driver PropertyMap has no to_dict(); cannot dump features"
                    )
                log.info("=== End Driver PropertyMap dump ===")
            except Exception as e:
                log.warning(f"Could not introspect driver_property_map: {e}")

            if self.pm:
                log.info("=== GenICam property dump BEGIN ===")
                if hasattr(self.pm, "to_dict"):
                    for pname, _ in self.pm.to_dict().items():
                        prop = self.pm.find(pname)
                        if prop and prop.is_available:
                            info = {
                                "value": prop.value,
                                "min": getattr(prop, "minimum", None),
                                "max": getattr(prop, "maximum", None),
                                "access": (
                                    "RW"
                                    if not getattr(prop, "is_readonly", True)
                                    else "RO"
                                ),
                                "type": type(prop.value).__name__,
                            }
                            log.info(f"  {pname}: {info}")
                else:
                    log.warning("PropertyMap has no to_dict(); cannot dump features")
                log.info("=== GenICam property dump END ===")
            else:
                log.error("PropertyMap is None; cannot list GenICam features")

            # 3) GigE optimizations: packet size & throughput limits
            try:
                psize = self.pm.find("GevSCPSPacketSize")
                if psize and psize.is_available:
                    jumbo = min(int(psize.maximum), 8228)
                    self.pm.set_value("GevSCPSPacketSize", jumbo)
                    log.info(f"Packet size set to {jumbo}")
            except Exception as e:
                log.warning(f"Could not set GevSCPSPacketSize: {e}")

            try:
                dlm = self.pm.find("DeviceLinkThroughputLimitMode")
                if dlm and dlm.is_available:
                    self.pm.set_value("DeviceLinkThroughputLimitMode", "Off")
                    log.info("Disabled throughput limit mode")
                dll = self.pm.find("DeviceLinkThroughputLimit")
                if dll and dll.is_available:
                    max_limit = int(dll.maximum)
                    self.pm.set_value("DeviceLinkThroughputLimit", max_limit)
                    log.info(f"Throughput limit set to {max_limit}")
            except Exception as e:
                log.warning(f"Could not set throughput limits: {e}")

            # 4) Enumerate and emit UI controls
            controls = {}
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
                    auto_val = auto_prop.value
                    exp_ctrl["is_auto_on"] = (
                        auto_val == "Continuous"
                        if isinstance(auto_val, str)
                        else bool(auto_val)
                    )
                controls["exposure"] = exp_ctrl
            gain_prop = self.pm.find(PROP_GAIN)
            if gain_prop and gain_prop.is_available:
                controls["gain"] = {
                    "enabled": True,
                    "min": float(gain_prop.minimum),
                    "max": float(gain_prop.maximum),
                    "value": float(gain_prop.value),
                }
            self.camera_properties_updated.emit({"controls": controls})

            # 5) Configure camera settings
            self._set(PROP_PIXEL_FORMAT, "Mono8")
            self._set(PROP_WIDTH, self.desired_width)
            self._set(PROP_HEIGHT, self.desired_height)
            fps_prop = self.pm.find(PROP_ACQUISITION_FRAME_RATE)
            if fps_prop and fps_prop.is_available:
                tgt = max(fps_prop.minimum, min(self.target_fps, fps_prop.maximum))
                self._set(PROP_ACQUISITION_FRAME_RATE, tgt)
            self._set(PROP_ACQUISITION_MODE, "Continuous")
            self._set(PROP_TRIGGER_MODE, "Off")

            # 6) Start streaming
            self.sink = ic4.QueueSink(self.listener)
            self.sink.timeout = 15000
            time.sleep(0.2)
            self.grabber.stream_setup(
                self.sink,
                setup_option=ic4.StreamSetupOption.ACQUISITION_START,
            )
            log.info("Streaming started—entering acquisition loop")

            # 7) Acquisition loop
            while not self._stop:
                try:
                    buf = self.sink.pop_output_buffer()
                except ic4.IC4Exception:
                    time.sleep(0.05)
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
                except Exception:
                    pass

            if self.grabber and getattr(self.grabber, "is_device_open", False):
                try:
                    self.grabber.device_close()
                except Exception:
                    pass
            log.info("Camera thread stopped")
