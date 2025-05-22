import logging
import time
import ctypes
import imagingcontrol4 as ic4

from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot
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

    def sink_disconnected(self, sink):
        log.debug("Sink disconnected")


class SDKCameraThread(QThread):
    # Signals
    camera_configured = pyqtSignal(object)  # Emits device_info
    frame_ready = pyqtSignal(QImage)  # Emits processed frame
    camera_properties_updated = pyqtSignal(dict)  # Emits {name: value}
    camera_error = pyqtSignal(str, str)  # Emits (message, code)

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
        self.target_fps = float(target_fps)
        self.desired_width = int(desired_width)
        self.desired_height = int(desired_height)
        self._stop = False
        self.grabber = None
        self.sink = None

    @pyqtSlot(str, object)
    def set_parameter(self, name: str, value: object):
        """
        Generic setter for any GenICam node.
        """
        success = False
        try:
            success = self._set(name, value)
        except Exception as e:
            log.error(f"Error in set_parameter for {name}: {e}")
        return success

    def _safe_init(self):
        try:
            ic4.Library.init()
        except Exception:
            pass

    def _set(self, name, val) -> bool:
        pm = self.grabber.device_property_map
        prop = pm.find(name)
        if not prop or not prop.is_available:
            log.warning(f"Property '{name}' unavailable.")
            return False
        try:
            # handle enums
            if isinstance(prop, ic4.PropEnumeration):
                for entry in prop.entries:
                    if entry.name == str(val):
                        prop.selected_entry = entry
                        break
            # numeric
            elif isinstance(prop, ic4.PropInteger):
                prop.value = int(val)
            elif isinstance(prop, ic4.PropFloat):
                prop.value = float(val)
            elif isinstance(prop, ic4.PropBoolean):
                prop.value = bool(val)
            elif isinstance(prop, ic4.PropString):
                prop.value = str(val)
            else:
                log.warning(f"Cannot set property type: {type(prop)}")
                return False

            log.info(f"Set '{name}' -> {val}")
            self.camera_properties_updated.emit({name: val})
            return True

        except Exception as e:
            log.error(f"Failed to set '{name}': {e}")
            return False

    def run(self):
        """
        Thread entry: open, configure, start streaming, emit frames.
        """
        self._safe_init()
        self.grabber = ic4.Grabber()
        try:
            # --- Open device ---
            if not self.device_info:
                devices = ic4.DeviceEnum.devices()
                if not devices:
                    raise RuntimeError("No cameras found.")
                self.device_info = devices[0]

            log.info(f"Opening device {self.device_info.model_name}")
            self.grabber.device_open(self.device_info)

            # --- Configure camera ---
            for name, val in [
                (PROP_PIXEL_FORMAT, "Mono8"),
                (PROP_WIDTH, self.desired_width),
                (PROP_HEIGHT, self.desired_height),
                (PROP_ACQUISITION_FRAME_RATE, self.target_fps),
                (PROP_ACQUISITION_MODE, "Continuous"),
                (PROP_TRIGGER_MODE, "Off"),
            ]:
                if not self._set(name, val):
                    log.warning(f"Config {name}->{val} may not be applied.")
                time.sleep(0.05)

            # --- Create sink & setup streaming ---
            self.sink = ic4.QueueSink(DummySinkListener())
            self.sink.timeout = 500
            self.grabber.stream_setup(self.sink)

            # Notify UI camera is ready
            self.camera_configured.emit(self.device_info)

            # --- Start acquisition ---
            try:
                self.grabber.start_acquisition()
            except AttributeError:
                self.grabber.start()

            # --- Frame loop ---
            while not self._stop:
                try:
                    buf = self.sink.pop_output_buffer()
                except ic4.IC4Exception as e:
                    # timeout OK
                    if getattr(e, "code", None) == ic4.ErrorCode.Timeout:
                        time.sleep(0.005)
                        continue
                    else:
                        raise

                if buf is None:
                    time.sleep(0.005)
                    continue

                # Convert to QImage
                w = buf.image_type.width
                h = buf.image_type.height
                pf = buf.image_type.pixel_format.name
                fmt = QImage.Format_Grayscale8 if "Mono" in pf else QImage.Format_RGB888

                # get raw bytes
                arr = buf.numpy_wrap() if hasattr(buf, "numpy_wrap") else None
                if arr is not None:
                    data = arr.tobytes()
                    stride = arr.strides[0]
                else:
                    pitch = getattr(buf, "pitch", w * buf.image_type.bytes_per_pixel)
                    data = ctypes.string_at(buf.pointer, pitch * h)
                    stride = pitch

                img = QImage(data, w, h, stride, fmt).copy()
                self.frame_ready.emit(img)

                buf.queue()

            # End loop

        except Exception as e:
            log.exception("Camera thread error")
            self.camera_error.emit(str(e), type(e).__name__)

        finally:
            # Stop acquisition & cleanup
            try:
                self.grabber.stop_acquisition()
            except Exception:
                try:
                    self.grabber.stop()
                except:
                    pass

            if self.grabber and self.grabber.is_device_open:
                try:
                    self.grabber.device_close()
                except:
                    pass

            log.info("SDKCameraThread finished.")
