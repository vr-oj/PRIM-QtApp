import logging
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal, QMutex
from PyQt5.QtGui import QImage
from imagingcontrol4.properties import (
    PropInteger,
    PropBoolean,
    PropFloat,
    PropEnumeration,
)

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    """
    Thread handling TIS SDK camera grab and emitting frames, resolutions, and properties.
    """

    # Signals for frame delivery, errors, resolutions, and properties
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
        self._mutex = QMutex()
        self._stop_requested = False
        self.target_fps = target_fps

        # Desired settings
        self.desired_width = width
        self.desired_height = height
        self.desired_pixel_format = pixel_format
        self.desired_exposure = exposure_us
        self.desired_gain = None
        self.desired_auto_exposure = None

        # Pending updates from the UI
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
        try:
            # ─── Enumerate and open camera ─────────────────────────
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

            # ─── Apply desired settings with safeguards ────────────
            if hasattr(ic4.PropId, "WIDTH"):
                try:
                    pm.set_value(ic4.PropId.WIDTH, self.desired_width)
                except Exception as e:
                    log.warning(f"Could not set WIDTH={self.desired_width}: {e}")
            if hasattr(ic4.PropId, "HEIGHT"):
                try:
                    pm.set_value(ic4.PropId.HEIGHT, self.desired_height)
                except Exception as e:
                    log.warning(f"Could not set HEIGHT={self.desired_height}: {e}")
            if hasattr(ic4.PropId, "EXPOSURE"):
                try:
                    pm.set_value(ic4.PropId.EXPOSURE, self.desired_exposure)
                except Exception as e:
                    log.warning(f"Could not set EXPOSURE={self.desired_exposure}: {e}")

            # ─── Start acquisition ──────────────────────────────────
            grabber.stream_start()
            import time

            last_time = time.time()
            while True:
                self._mutex.lock()
                if self._stop_requested:
                    self._mutex.unlock()
                    break
                self._mutex.unlock()

                # Pending UI updates
                if self._pending_exposure is not None and hasattr(
                    ic4.PropId, "EXPOSURE"
                ):
                    try:
                        pm.set_value(ic4.PropId.EXPOSURE, self._pending_exposure)
                    except Exception as e:
                        log.warning(f"Error updating exposure: {e}")
                    self._pending_exposure = None
                if self._pending_gain is not None and hasattr(ic4.PropId, "GAIN"):
                    try:
                        pm.set_value(ic4.PropId.GAIN, self._pending_gain)
                    except Exception as e:
                        log.warning(f"Error updating gain: {e}")
                    self._pending_gain = None
                if self._pending_auto_exposure is not None and hasattr(
                    ic4.PropId, "EXPOSURE_AUTO"
                ):
                    try:
                        pm.set_value(
                            ic4.PropId.EXPOSURE_AUTO, self._pending_auto_exposure
                        )
                    except Exception as e:
                        log.warning(f"Error updating auto_exposure: {e}")
                    self._pending_auto_exposure = None

                # Snap a frame
                result = grabber.snap_single(ic4.Timeout(1000))
                if result.is_ok:
                    img = result.image
                    frame = img.as_bytearray()
                    qimg = QImage(frame, img.width, img.height, QImage.Format_Indexed8)
                    self.frame_ready.emit(qimg.copy(), frame.copy())
                else:
                    log.warning("Frame grab timeout or error.")

                # Throttle to target FPS
                elapsed = time.time() - last_time
                to_sleep = max(0, (1.0 / self.target_fps) - elapsed)
                if to_sleep > 0:
                    time.sleep(to_sleep)
                last_time = time.time()

        except Exception as e:
            log.exception(f"Error in SDKCameraThread: {e}")
            try:
                self.camera_error.emit(str(e), type(e).__name__)
            except Exception:
                pass
        finally:
            # Clean up
            if grabber:
                try:
                    if grabber.is_streaming:
                        grabber.stream_stop()
                    if grabber.is_device_open:
                        grabber.device_close()
                except Exception:
                    pass
            log.info("Camera thread finished.")

    def stop(self):
        self._mutex.lock()
        self._stop_requested = True
        self._mutex.unlock()
