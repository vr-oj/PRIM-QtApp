import logging
import imagingcontrol4 as ic4
import time
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage
from imagingcontrol4 import BufferSink, StreamSetupOption, ErrorCode, IC4Exception
from imagingcontrol4.properties import (
    PropInteger,
    PropFloat,
    PropBoolean,
    PropEnumeration,
)

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    """
    Thread handling TIS SDK camera grab and emitting live frames and camera properties.
    Uses BufferSink for continuous streaming and frames with wait_for_buffer.
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
        self._pending_exposure = None
        self._pending_gain = None
        self._pending_auto = None

    def update_exposure(self, exp_us: int):
        self._pending_exposure = exp_us

    def update_gain(self, gain: int):
        self._pending_gain = gain

    def update_auto_exposure(self, auto: bool):
        self._pending_auto = auto

    def run(self):
        grabber = None
        sink = None
        try:
            # 1. Enumerate cameras
            devices = ic4.DeviceEnum.devices()
            if not devices:
                raise RuntimeError("No TIS cameras found.")
            dev = devices[0]
            log.info(f"Opening camera: {dev.model_name} (S/N {dev.serial})")

            # 2. Open grabber and property map
            grabber = ic4.Grabber()
            grabber.device_open(dev)
            pm = grabber.device_property_map

            # 3. Emit current resolution
            try:
                w = pm.get_value(ic4.PropId.WIDTH)
                h = pm.get_value(ic4.PropId.HEIGHT)
                self.camera_resolutions_available.emit([(w, h)])
            except Exception:
                log.warning("Failed to read current resolution.")

            # 4. Emit camera controls
            controls = {}
            for name, pid in [
                ("exposure", ic4.PropId.EXPOSURE),
                ("gain", ic4.PropId.GAIN),
                ("auto_exposure", ic4.PropId.EXPOSURE_AUTO),
            ]:
                try:
                    prop = pm.find(pid)
                    if isinstance(prop, PropInteger) or isinstance(prop, PropFloat):
                        controls[name] = {
                            "enabled": True,
                            "min": prop.minimum,
                            "max": prop.maximum,
                            "value": prop.value,
                        }
                    elif isinstance(prop, PropBoolean):
                        controls[name] = {"enabled": True, "value": prop.value}
                    elif isinstance(prop, PropEnumeration):
                        controls[name] = {
                            "enabled": True,
                            "options": prop.options,
                            "value": prop.get_value_str(),
                        }
                except Exception:
                    pass
            self.camera_properties_updated.emit(controls)

            # 5. Set initial width/height/exposure
            for pid, val in [
                (ic4.PropId.WIDTH, self.desired_width),
                (ic4.PropId.HEIGHT, self.desired_height),
                (ic4.PropId.EXPOSURE, self.desired_exposure),
            ]:
                try:
                    pm.set_value(pid, val)
                except Exception as e:
                    log.warning(f"Could not set {pid}: {e}")

            # 6. Setup continuous stream
            sink = BufferSink()
            grabber.stream_setup(sink, setup_option=StreamSetupOption.ACQUISITION_START)
            grabber.stream_start()
            log.info("Streaming started.")

            # 7. Frame loop
            last = time.time()
            while not self._stop_requested:
                # pending updates
                if self._pending_exposure is not None:
                    try:
                        pm.set_value(ic4.PropId.EXPOSURE, self._pending_exposure)
                    except:
                        pass
                    self._pending_exposure = None
                if self._pending_gain is not None:
                    try:
                        pm.set_value(ic4.PropId.GAIN, self._pending_gain)
                    except:
                        pass
                    self._pending_gain = None
                if self._pending_auto is not None:
                    try:
                        pm.set_value(ic4.PropId.EXPOSURE_AUTO, self._pending_auto)
                    except:
                        pass
                    self._pending_auto = None

                # wait for buffer
                buf = sink.wait_for_buffer(timeout_ms=1000)
                if buf is None:
                    log.warning("Buffer timeout.")
                else:
                    data = buf.buffer
                    stride = getattr(buf, "stride", buf.width)
                    qimg = QImage(
                        data, buf.width, buf.height, stride, QImage.Format_Grayscale8
                    )
                    if not qimg.isNull():
                        self.frame_ready.emit(qimg.copy(), None)
                    else:
                        log.warning("Invalid QImage.")

                # throttle FPS
                dt = time.time() - last
                to_sleep = max(0, (1 / self.target_fps) - dt)
                if to_sleep > 0:
                    self.msleep(int(to_sleep * 1000))
                last = time.time()

        except IC4Exception as e:
            log.error(f"IC4Exception: {e} (Code: {e.code})")
            self.camera_error.emit(str(e), type(e).__name__)
        except Exception as e:
            log.exception(f"Camera thread error: {e}")
            self.camera_error.emit(str(e), type(e).__name__)
        finally:
            if grabber:
                try:
                    grabber.stream_stop()
                except:
                    pass
                try:
                    grabber.device_close()
                except:
                    pass
            log.info("Camera thread stopped.")

    def stop(self):
        """Signal the thread to stop; caller should wait() after."""
        self._stop_requested = True
