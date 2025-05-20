import logging
import time
import ctypes
import imagingcontrol4 as ic4

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)

# GenICam camera-property names
PROP_WIDTH = "Width"
PROP_HEIGHT = "Height"
PROP_PIXEL_FORMAT = "PixelFormat"
PROP_OFFSET_X = "OffsetX"
PROP_OFFSET_Y = "OffsetY"
PROP_ACQUISITION_MODE = "AcquisitionMode"
PROP_TRIGGER_MODE = "TriggerMode"


class SDKCameraThread(QThread):
    """
    Simplified camera thread: always picks first available device,
    configures it to full sensor, continuous free-run, and streams frames.
    """

    frame_ready = pyqtSignal(QImage, object)
    camera_error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_requested = False

    def request_stop(self):
        self._stop_requested = True
        log.debug("Camera thread stop requested")

    def run(self):
        try:
            # Ensure library initialized
            try:
                ic4.Library.init()
            except Exception:
                pass
            # Enumerate and open first device
            devs = ic4.DeviceEnum.devices()
            if not devs:
                raise RuntimeError("No camera found")
            grabber = ic4.Grabber()
            grabber.device_open(devs[0])
            pm = grabber.device_property_map
            log.info(f"Opened camera: {devs[0].model_name}")

            # Set pixel format to first available
            pfp = pm.find(PROP_PIXEL_FORMAT)
            if hasattr(pfp, "entries") and pfp.entries:
                first_pf = pfp.entries[0].name
                try:
                    pm.set_value(PROP_PIXEL_FORMAT, first_pf)
                    log.info(f"PixelFormat set to {first_pf}")
                except Exception:
                    log.warning(f"Could not set PixelFormat to {first_pf}")

            # Full sensor dims
            wp = pm.find(PROP_WIDTH)
            hp = pm.find(PROP_HEIGHT)
            try:
                if hasattr(wp, "maximum"):
                    pm.set_value(PROP_WIDTH, wp.maximum)
                if hasattr(hp, "maximum"):
                    pm.set_value(PROP_HEIGHT, hp.maximum)
                pm.set_value(PROP_OFFSET_X, 0)
                pm.set_value(PROP_OFFSET_Y, 0)
                log.info(f"Full sensor: {wp.maximum}×{hp.maximum}")
            except Exception:
                log.warning("Could not set full sensor ROI, proceeding")

            # Continuous, free-run
            try:
                pm.set_value(PROP_ACQUISITION_MODE, "Continuous")
                pm.set_value(PROP_TRIGGER_MODE, "Off")
            except Exception:
                log.warning("Could not set acquisition mode/trigger, proceeding")

            # Start streaming
            listener = ic4.QueueSink(self)
            listener.accept_incomplete_frames = False
            grabber.stream_setup(
                listener, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            log.info("Streaming started")

            # Grab loop
            while not self._stop_requested:
                try:
                    buf = listener.pop_output_buffer()
                except Exception:
                    time.sleep(0.01)
                    continue
                if buf is None:
                    continue
                # Build QImage
                w = buf.image_type.width
                h = buf.image_type.height
                try:
                    if hasattr(buf, "numpy_wrap"):
                        arr = buf.numpy_wrap()
                        raw = arr.tobytes()
                        stride = arr.strides[0]
                        fmt = (
                            QImage.Format_Grayscale8
                            if arr.ndim == 2
                            else QImage.Format_RGB888
                        )
                    else:
                        pitch = getattr(buf, "pitch", w)
                        raw = ctypes.string_at(buf.pointer, pitch * h)
                        stride = pitch
                        fmt = QImage.Format_Grayscale8
                    img = QImage(raw, w, h, stride, fmt)
                    if not img.isNull():
                        self.frame_ready.emit(img.copy(), raw)
                except Exception:
                    log.exception("Failed to build QImage")
                finally:
                    try:
                        buf.release()
                    except Exception:
                        pass

        except Exception as e:
            log.exception("Camera thread error")
            self.camera_error.emit(str(e), type(e).__name__)

        finally:
            try:
                if isinstance(grabber, ic4.Grabber):
                    if getattr(grabber, "is_streaming", False):
                        grabber.stream_stop()
                    if getattr(grabber, "is_device_open", False):
                        grabber.device_close()
            except Exception:
                pass
            log.info("Camera thread stopped")
