import logging
import imagingcontrol4 as ic4
import time
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
        sink = None
        streaming = False
        try:
            # Enumerate and open camera
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

            # Gather and emit initial properties
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

            # Emit current resolution
            try:
                w = pm.get_value(ic4.PropId.WIDTH)
                h = pm.get_value(ic4.PropId.HEIGHT)
                self.camera_resolutions_available.emit([(w, h)])
            except Exception:
                pass

            # Safely apply initial settings
            for pid_attr, value in [
                ("WIDTH", self.desired_width),
                ("HEIGHT", self.desired_height),
                ("EXPOSURE", self.desired_exposure),
            ]:
                if hasattr(ic4.PropId, pid_attr):
                    try:
                        pm.set_value(getattr(ic4.PropId, pid_attr), value)
                    except Exception as e:
                        log.warning(f"Could not set {pid_attr}={value}: {e}")

            # Prepare SnapSink
            sink = ic4.SnapSink()
            try:
                grabber.stream_setup(
                    sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
                )
                streaming = True
                log.info("Streaming mode enabled.")
            except Exception as e:
                log.warning(f"Streaming setup failed, falling back to snap_single: {e}")

            # Frame acquisition loop
            last_time = time.time()
            while True:
                with self._mutex:
                    if self._stop_requested:
                        break

                # Handle pending UI updates with availability checks
                if self._pending_exposure is not None:
                    try:
                        if pm.is_property_available(ic4.PropId.EXPOSURE):
                            pm.set_value(ic4.PropId.EXPOSURE, self._pending_exposure)
                        else:
                            log.warning("Exposure property not available to update.")
                    except Exception as e:
                        log.warning(f"Error updating exposure: {e}")
                    self._pending_exposure = None
                if self._pending_gain is not None:
                    try:
                        if pm.is_property_available(ic4.PropId.GAIN):
                            pm.set_value(ic4.PropId.GAIN, self._pending_gain)
                        else:
                            log.warning("Gain property not available to update.")
                    except Exception as e:
                        log.warning(f"Error updating gain: {e}")
                    self._pending_gain = None
                if self._pending_auto_exposure is not None:
                    try:
                        if pm.is_property_available(ic4.PropId.EXPOSURE_AUTO):
                            pm.set_value(
                                ic4.PropId.EXPOSURE_AUTO, self._pending_auto_exposure
                            )
                        else:
                            log.warning(
                                "Auto Exposure property not available to update."
                            )
                    except Exception as e:
                        log.warning(f"Error updating auto_exposure: {e}")
                    self._pending_auto_exposure = None

                # Acquire frame
                try:
                    image_buffer = sink.snap_single(1000)
                    frame_array = image_buffer.as_bytearray()
                    qimg = QImage(
                        frame_array,
                        image_buffer.width,
                        image_buffer.height,
                        image_buffer.width,
                        QImage.Format_Indexed8,
                    )
                    if qimg.isNull():
                        log.warning("Created QImage is null. Check frame parameters.")
                    else:
                        self.frame_ready.emit(qimg.copy(), frame_array)
                except ic4.IC4Exception as e:
                    if e.code == ic4.ErrorCode.Timeout:
                        log.warning("Frame grab timeout using snap_single.")
                    else:
                        log.error(
                            f"IC4Exception during snap_single: {e} (Code: {e.code})"
                        )
                except Exception as e:
                    log.exception(f"Unexpected error in frame acquisition: {e}")

                # Throttle FPS
                elapsed = time.time() - last_time
                to_sleep = max(0, (1.0 / self.target_fps) - elapsed)
                if to_sleep > 0:
                    self.msleep(int(to_sleep * 1000))
                last_time = time.time()

        except RuntimeError as e:
            log.error(f"RuntimeError in SDKCameraThread: {e}")
            try:
                self.camera_error.emit(str(e), type(e).__name__)
            except Exception:
                pass
        except Exception as e:
            log.exception(f"Error in SDKCameraThread setup: {e}")
            try:
                self.camera_error.emit(str(e), type(e).__name__)
            except Exception:
                pass
        finally:
            # Clean up resources
            if sink:
                try:
                    sink.release()
                except Exception as e_release:
                    log.error(f"Error releasing sink: {e_release}")
            if streaming:
                try:
                    grabber.stream_stop()
                except Exception as e_stop:
                    log.error(f"Error stopping stream: {e_stop}")
            if grabber and getattr(grabber, "is_device_open", lambda: False)():
                try:
                    grabber.device_close()
                except Exception as e_close:
                    log.error(f"Error closing device: {e_close}")
            log.info("Camera thread finished.")

    def stop(self):
        with self._mutex:
            self._stop_requested = True
