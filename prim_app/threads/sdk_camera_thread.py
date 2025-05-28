import re
import numpy as np
import logging
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class MinimalSinkListener(ic4.QueueSinkListener):
    def __init__(self, owner_name="DefaultListener"):
        super().__init__()
        self.owner_name = owner_name
        log.debug(f"MinimalSinkListener '{self.owner_name}' created.")

    def frame_ready(self, sink: ic4.QueueSink, buffer: ic4.ImageBuffer, userdata: any):
        pass

    def frames_queued(self, sink: ic4.QueueSink):
        pass

    def sink_connected(
        self, sink: ic4.QueueSink, image_type_proposed: ic4.ImageType, userdata: any
    ) -> bool:
        log.debug(
            f"Listener '{self.owner_name}': Sink connected. Grabber proposed ImageType: {image_type_proposed}. Accepting."
        )
        return True

    def sink_disconnected(self, sink: ic4.QueueSink):
        log.debug(f"Listener '{self.owner_name}': Sink disconnected from {sink}.")

    def sink_property_changed(
        self, sink: ic4.QueueSink, property_name: str, userdata: any
    ):
        pass


class SDKCameraThread(QThread):
    frame_ready = pyqtSignal(QImage, object)
    camera_error = pyqtSignal(str, str)
    camera_info_updated = pyqtSignal(dict)
    exposure_params_updated = pyqtSignal(dict)

    def __init__(self, device_name=None, fps=10, parent=None):
        super().__init__(parent)
        self.device_identifier = device_name
        self.target_fps = float(fps)
        self._stop_requested = False
        self.grabber = None
        self.pm = None
        self.sink_listener = MinimalSinkListener(
            f"SDKThreadListener_{self.device_identifier or 'default'}"
        )
        log.info(
            f"SDKCameraThread initialized for '{self.device_identifier}', target_fps: {self.target_fps}"
        )

    def _attempt_set_property(
        self, prop_name: str, value_to_set: any, readable_value_for_log: str = None
    ):
        if readable_value_for_log is None:
            readable_value_for_log = str(value_to_set)
        if not self.pm:
            log.error(f"PM not avail for {prop_name}.")
            return False
        try:
            prop_item = self.pm.find(prop_name)
            if prop_item:
                log.info(f"Setting {prop_name} to {readable_value_for_log}...")
                self.pm.set_value(prop_name, value_to_set)
                log.info(f"Property {prop_name} set.")
                return True
            else:
                log.warning(f"Property {prop_name} not found.")
                return False
        except Exception as e:
            log.error(f"Error setting {prop_name}: {e}")
            return False

    def _query_and_emit_camera_parameters(self):
        """Queries key camera parameters and emits them via signals."""
        if not self.pm:
            log.warning("Cannot query camera parameters: PropertyMap not available.")
            return
        # General camera info
        info = {}

        def safe_read(prop, as_str=False, default=None):
            if not prop:
                return default
            try:
                if as_str and hasattr(prop, "value_to_str"):
                    return prop.value_to_str()
                return prop.value
            except Exception as e:
                log.warning(f"Unable to read {prop.name}: {e}")
                return default

        camera_props = [
            ("model", "DeviceModelName", True),
            ("serial", "DeviceSerialNumber", True),
            ("width", "Width", False),
            ("height", "Height", False),
            ("pixel_format", "PixelFormat", True),
            ("fps", "AcquisitionFrameRate", False),
        ]
        for key, name, is_str in camera_props:
            prop = self.pm.find(name)
            info[key] = safe_read(prop, as_str=is_str, default=None)
        self.camera_info_updated.emit(info)
        log.debug(f"camera_info_updated: {info}")
        # Exposure parameters
        exp = {
            "auto_options": [],
            "auto_current": None,
            "auto_is_writable": False,
            "time_current_us": None,
            "time_min_us": None,
            "time_max_us": None,
            "time_is_writable": False,
        }
        p_auto = self.pm.find("ExposureAuto")
        if p_auto:
            exp["auto_is_writable"] = getattr(p_auto, "is_writable", False)
            try:
                exp["auto_current"] = p_auto.value_to_str()
            except Exception:
                exp["auto_current"] = None
            exp["auto_options"] = [
                e.name for e in getattr(p_auto, "available_entries", [])
            ]
        p_time = self.pm.find("ExposureTime")
        if p_time:
            # allow time control whenever auto is off
            exp["time_is_writable"] = (
                True
                if exp["auto_current"] == "Off"
                else getattr(p_time, "is_writable", False)
            )
            try:
                exp["time_current_us"] = p_time.value
            except Exception:
                exp["time_current_us"] = None
            # try common range attrs
            exp["time_min_us"] = getattr(p_time, "min", None) or getattr(
                p_time, "minimum", None
            )
            exp["time_max_us"] = getattr(p_time, "max", None) or getattr(
                p_time, "maximum", None
            )
            # fallback defaults
            if exp["time_min_us"] is None:
                exp["time_min_us"] = 1.0
            if exp["time_max_us"] is None:
                exp["time_max_us"] = exp["time_current_us"] or 1000000.0
        self.exposure_params_updated.emit(exp)
        log.debug(f"exposure_params_updated: {exp}")

    @pyqtSlot(str)
    def set_exposure_auto(self, mode: str):
        if self.pm and self.pm.find("ExposureAuto"):
            self._attempt_set_property("ExposureAuto", mode, mode)
            self._query_and_emit_camera_parameters()
        else:
            log.warning("ExposureAuto property unavailable.")

    @pyqtSlot(float)
    def set_exposure_time(self, us: float):
        if self.pm and self.pm.find("ExposureTime"):
            self._attempt_set_property("ExposureTime", us, f"{us}us")
            self._query_and_emit_camera_parameters()
        else:
            log.warning("ExposureTime property unavailable.")

    def run(self):
        try:
            devices = ic4.DeviceEnum.devices()
            if not devices:
                raise RuntimeError("No IC4 devices found.")
            target = None
            if self.device_identifier:
                for d in devices:
                    if self.device_identifier in (
                        getattr(d, "serial", ""),
                        getattr(d, "unique_name", ""),
                        getattr(d, "model_name", ""),
                    ):
                        target = d
                        break
                if not target:
                    raise RuntimeError(f"Camera '{self.device_identifier}' not found.")
            else:
                target = devices[0]
            self.grabber = ic4.Grabber()
            self.grabber.device_open(target)
            self.pm = self.grabber.device_property_map
            # default config
            self._attempt_set_property("PixelFormat", ic4.PixelFormat.Mono8, "Mono8")
            self._attempt_set_property("Width", 640, "640")
            self._attempt_set_property("Height", 480, "480")
            self._attempt_set_property("AcquisitionMode", "Continuous", "Continuous")
            self._attempt_set_property("TriggerMode", "Off", "Off")
            self._attempt_set_property("ExposureAuto", "Off", "Off")
            # emit initial parameters
            self._query_and_emit_camera_parameters()
            # start streaming
            self.sink = ic4.QueueSink(listener=self.sink_listener)
            self.grabber.stream_setup(self.sink)
            if not self.grabber.is_acquisition_active:
                self.grabber.acquisition_start()
            while not self._stop_requested:
                try:
                    buf = self.sink.pop_output_buffer()
                    if not buf:
                        QThread.msleep(10)
                        continue
                    arr = buf.numpy_wrap()
                    fmt = (
                        QImage.Format_BGR888
                        if (arr.ndim == 3 and arr.shape[2] == 3)
                        else QImage.Format_Grayscale8
                    )
                    qimg = QImage(
                        arr.data, arr.shape[1], arr.shape[0], arr.strides[0], fmt
                    )
                    self.frame_ready.emit(qimg.copy(), arr.copy())
                    buf.release()
                except ic4.IC4Exception as e:
                    if e.code in (ic4.ErrorCode.Timeout, ic4.ErrorCode.NoData):
                        QThread.msleep(5)
                        continue
                    log.error(f"IC4Exception in loop: {e}")
                    self.camera_error.emit(str(e), str(e.code))
                    break
                except Exception as e:
                    log.error(f"Error in frame loop: {e}")
                    self.camera_error.emit(str(e), type(e).__name__)
                    break
        except Exception as e:
            log.error(f"SDKCameraThread.run error: {e}")
            self.camera_error.emit(str(e), type(e).__name__)
        finally:
            try:
                if self.grabber and self.grabber.is_acquisition_active:
                    self.grabber.acquisition_stop()
                if self.grabber and self.grabber.is_device_open:
                    self.grabber.device_close()
            except Exception as e:
                log.error(f"Cleanup error: {e}")
            self.grabber = None
            self.pm = None
            log.info("SDKCameraThread cleanup complete.")

    def stop(self):
        log.info(f"Stopping SDKCameraThread for {self.device_identifier}.")
        self._stop_requested = True
        if self.isRunning() and not self.wait(3000):
            log.warning("Thread did not stop in time, terminating.")
            self.terminate()
            self.wait(500)
