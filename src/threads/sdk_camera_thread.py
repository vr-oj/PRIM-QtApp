import logging
import imagingcontrol4 as ic4
import time
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage
from imagingcontrol4 import SnapSink, StreamSetupOption, ErrorCode, IC4Exception
from imagingcontrol4.properties import (
    PropInteger,
    PropBoolean,
    PropFloat,
    PropEnumeration,
)

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    """
    Thread handling TIS SDK camera grab and emitting live frames and camera properties.
    Uses SnapSink + stream_setup + stream_start for continuous capture.
    """

    frame_ready = pyqtSignal(QImage, object)
    camera_resolutions_available = pyqtSignal(list)
    camera_properties_updated = pyqtSignal(dict)
    camera_error = pyqtSignal(str, str)

    def __init__(
        self,
        exposure_us=20000,
        target_fps=20,
        width=640,
        height=480,
        pixel_format="Mono8",
        parent=None,
    ):
        super().__init__(parent)
        self._stop_requested = False
        self.target_fps = target_fps
        self.desired_width = width
        self.desired_height = height
        self.desired_pixel_format = pixel_format
        self.desired_exposure = exposure_us
        self.desired_gain = None
        self.desired_auto_exposure = None
        self._pending_exposure = None
        self._pending_gain = None
        self._pending_auto_exposure = None

    def update_exposure(self, new_exp_us: int):
        self._pending_exposure = new_exp_us

    def update_gain(self, new_gain: int):
        self._pending_gain = new_gain

    def update_auto_exposure(self, enable: bool):
        self._pending_auto_exposure = enable

    def run(self):
        self._stop_requested = False
        grabber = None
        sink = None
        try:
            # Enumerate and open device
            devices = ic4.DeviceEnum.devices()
            if not devices:
                raise RuntimeError("No TIS cameras found - please connect a camera.")
            for idx, dev in enumerate(devices):
                log.info(f"Camera device {idx}: {dev.model_name} (S/N {dev.serial})")
            dev = devices[0]
            log.info(f"Selected camera [0]: {dev.model_name} (S/N {dev.serial})")

            grabber = ic4.Grabber()
            grabber.device_open(dev)
            pm = grabber.device_property_map

            # Emit initial camera properties
            controls = {}

            def try_prop(name, pid):
                try:
                    prop = pm.find(pid)
                    if isinstance(prop, PropInteger):
                        controls[name] = {
                            "enabled": True,
                            "min": int(prop.minimum),
                            "max": int(prop.maximum),
                            "value": int(prop.value),
                        }
                    elif isinstance(prop, PropFloat):
                        controls[name] = {
                            "enabled": True,
                            "min": float(prop.minimum),
                            "max": float(prop.maximum),
                            "value": float(prop.value),
                        }
                    elif isinstance(prop, PropBoolean):
                        controls[name] = {"enabled": True, "value": bool(prop.value)}
                    elif isinstance(prop, PropEnumeration):
                        controls[name] = {
                            "enabled": True,
                            "options": prop.options,
                            "value": prop.get_value_str(),
                        }
                except Exception:
                    pass

            prop_map = {
                "width": "WIDTH",
                "height": "HEIGHT",
                "exposure": "EXPOSURE",
                "gain": "GAIN",
                "auto_exposure": "EXPOSURE_AUTO",
            }
            for name, attr in prop_map.items():
                if hasattr(ic4.PropId, attr):
                    try_prop(name, getattr(ic4.PropId, attr))
            self.camera_properties_updated.emit(controls)

            # Emit available resolution
            try:
                w = pm.get_value(ic4.PropId.WIDTH)
                h = pm.get_value(ic4.PropId.HEIGHT)
                self.camera_resolutions_available.emit([(w, h)])
            except Exception:
                pass

            # Apply initial settings
            for pid_attr, value in [
                ("WIDTH", self.desired_width),
                ("HEIGHT", self.desired_height),
                ("EXPOSURE", self.desired_exposure),
            ]:
                pid = getattr(ic4.PropId, pid_attr, None)
                if pid:
                    try:
                        pm.set_value(pid, value)
                    except Exception as e:
                        log.warning(f"Could not set {pid_attr}={value}: {e}")

            # Setup streaming sink
            sink = SnapSink()
            grabber.stream_setup(sink, setup_option=StreamSetupOption.ACQUISITION_START)
            grabber.stream_start()
            log.info("Streaming started via SnapSink.")

            last_time = time.time()
            while not self._stop_requested:
                # Handle pending updates
                if self._pending_exposure is not None:
                    try:
                        pm.set_value(ic4.PropId.EXPOSURE, self._pending_exposure)
                    except Exception as e:
                        log.warning(f"Error updating exposure: {e}")
                    self._pending_exposure = None
                if self._pending_gain is not None:
                    try:
                        pm.set_value(ic4.PropId.GAIN, self._pending_gain)
                    except Exception as e:
                        log.warning(f"Error updating gain: {e}")
                    self._pending_gain = None
                if self._pending_auto_exposure is not None:
                    try:
                        pm.set_value(
                            ic4.PropId.EXPOSURE_AUTO, self._pending_auto_exposure
                        )
                    except Exception as e:
                        log.warning(f"Error updating auto exposure: {e}")
                    self._pending_auto_exposure = None

                # Grab a frame
                try:
                    img_buf = sink.snap_single(1000)
                    if hasattr(img_buf, "as_bytearray"):
                        data = img_buf.as_bytearray()
                    elif hasattr(img_buf, "buffer"):
                        data = bytearray(img_buf.buffer)
                    else:
                        data = bytes(img_buf)
                    stride = getattr(img_buf, "stride", img_buf.width)
                    qimg = QImage(
                        data,
                        img_buf.width,
                        img_buf.height,
                        stride,
                        QImage.Format_Indexed8,
                    )
                    if not qimg.isNull():
                        self.frame_ready.emit(qimg.copy(), None)
                    else:
                        log.warning("Null QImage from buffer.")
                except IC4Exception as e:
                    if e.code == ErrorCode.Timeout:
                        log.warning("Frame grab timeout.")
                    else:
                        log.error(f"IC4Exception in snap_single: {e} (Code: {e.code})")
                except Exception as e:
                    log.exception(f"Unexpected error grabbing frame: {e}")

                # Throttle to target FPS
                elapsed = time.time() - last_time
                delay = max(0, (1.0 / self.target_fps) - elapsed)
                if delay > 0:
                    self.msleep(int(delay * 1000))
                last_time = time.time()

        except IC4Exception as e:
            log.error(f"IC4Exception: {e} (Code: {e.code})")
            self.camera_error.emit(str(e), type(e).__name__)
        except RuntimeError as e:
            log.error(f"RuntimeError: {e}")
            self.camera_error.emit(str(e), type(e).__name__)
        except Exception as e:
            log.exception(f"Error in SDKCameraThread: {e}")
            self.camera_error.emit(str(e), type(e).__name__)
        finally:
            try:
                grabber.stream_stop()
            except Exception:
                pass
            try:
                grabber.device_close()
            except Exception:
                pass
            log.info("Camera thread finished.")

    def stop(self):
        """
        Request thread stop; caller should then wait() on the thread.
        """
        self._stop_requested = True
