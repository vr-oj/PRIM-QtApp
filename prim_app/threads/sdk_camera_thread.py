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
    gain_params_updated = pyqtSignal(dict)
    fps_params_updated = pyqtSignal(dict)
    pixel_format_options_updated = pyqtSignal(list, str)
    resolution_params_updated = pyqtSignal(dict)

    def __init__(self, device_name=None, fps=10, parent=None):
        super().__init__(parent)
        self.device_identifier = device_name
        self.initial_target_fps = float(fps)
        self._stop_requested = False
        self.grabber = None
        self.pm = None
        self.sink_listener = MinimalSinkListener(
            f"SDKThreadListener_{self.device_identifier or 'default'}"
        )
        log.info(
            f"SDKCameraThread initialized for '{self.device_identifier}', initial_target_fps: {self.initial_target_fps}"
        )

    def _is_property_writable(self, prop_item, prop_name_for_log="Property"):
        """Checks if a property item is writable."""
        if not prop_item:
            return False

        is_writable_attr = getattr(prop_item, "is_writable", None)
        is_read_only_attr = getattr(prop_item, "is_read_only", None)

        if is_writable_attr is not None:
            return is_writable_attr
        elif is_read_only_attr is not None:
            return not is_read_only_attr
        else:
            log.warning(
                f"{prop_name_for_log} has neither is_writable nor is_read_only attribute. Assuming not writable."
            )
            return False

    def _attempt_set_property(
        self, prop_name: str, value_to_set: any, readable_value_for_log: str = None
    ):
        if readable_value_for_log is None:
            readable_value_for_log = str(value_to_set)
        if not self.pm:
            log.error(f"PropertyMap not available. Cannot set {prop_name}.")
            return False

        prop_item = None
        try:
            prop_item = self.pm.find(prop_name)
            if prop_item:
                if self._is_property_writable(prop_item, prop_name):
                    log.info(f"Setting {prop_name} to {readable_value_for_log}...")
                    self.pm.set_value(prop_name, value_to_set)
                    log.info(f"Property {prop_name} set successfully.")
                    return True
                else:
                    log.warning(f"Property {prop_name} is not writable.")
                    return False
            else:
                log.warning(f"Property {prop_name} not found in PropertyMap.")
                return False
        except ic4.IC4Exception as e_ic4:  # Catch specific IC4 exceptions
            if e_ic4.code == ic4.ErrorCode.GenICamFeatureNotFound:
                log.warning(
                    f"Feature {prop_name} not found on this camera (GenICamFeatureNotFound)."
                )
            else:
                log.error(
                    f"IC4Exception setting {prop_name} to {readable_value_for_log}: {e_ic4} (Code: {e_ic4.code})"
                )
        except Exception as e:  # Catch other exceptions
            log.error(
                f"Generic error setting {prop_name} to {readable_value_for_log}: {e}"
            )
        return False

    def _safe_get_attr(self, prop_item, attr_name, default=None):
        """Helper to safely read property attributes like min, max, etc."""
        if prop_item and hasattr(prop_item, attr_name):
            try:
                return getattr(prop_item, attr_name)
            except Exception as e_attr:
                log.debug(
                    f"Could not read attr {attr_name} from {prop_item.name if hasattr(prop_item,'name') else 'property'}: {e_attr}"
                )
        return default

    def _safe_read_value(self, prop_item, as_str=False, default=None):
        """Helper to safely read property value."""
        if not prop_item:
            return default
        try:
            # For Enumeration properties, .string attribute gives current value as string.
            # For String properties, .value attribute IS the string.
            # For other properties, .value is the native type.
            if as_str:
                prop_type_name = getattr(
                    prop_item, "type_name", ""
                ).upper()  # Get property type string
                if "ENUM" in prop_type_name and hasattr(
                    prop_item, "string"
                ):  # Check for ENUMERATION type
                    return prop_item.string
                else:  # For STRING or other types, str(.value)
                    return str(prop_item.value)
            return prop_item.value
        except Exception as e_val:
            prop_name_for_log = getattr(prop_item, "name", "property")
            prop_type_for_log = getattr(prop_item, "type_name", "N/A")
            log.debug(
                f"Could not read value from {prop_name_for_log} (type: {prop_type_for_log}): {e_val}"
            )
        return default

    def _query_and_emit_camera_parameters(self):
        if not self.pm:
            log.warning("Cannot query camera parameters: PropertyMap not available.")
            return

        info = {}
        cam_props_for_info = [
            ("model", "DeviceModelName", True, "N/A"),
            ("serial", "DeviceSerialNumber", True, "N/A"),
            ("width", "Width", False, 0),
            ("height", "Height", False, 0),
            ("pixel_format", "PixelFormat", True, "N/A"),
            ("fps", "AcquisitionFrameRate", False, 0.0),
        ]
        for key, name, is_str, default_val in cam_props_for_info:
            prop = self.pm.find(name)
            info[key] = self._safe_read_value(prop, as_str=is_str, default=default_val)
        self.camera_info_updated.emit(info)
        log.debug(f"Emitted camera_info_updated: {info}")

        exp_params = {
            "auto_options": [],
            "auto_current": "Off",
            "auto_is_writable": False,
            "time_current_us": 0.0,
            "time_min_us": 1.0,
            "time_max_us": 1000000.0,
            "time_is_writable": False,
        }
        p_auto_exp = self.pm.find("ExposureAuto")
        if p_auto_exp:
            exp_params["auto_is_writable"] = self._is_property_writable(
                p_auto_exp, "ExposureAuto"
            )
            exp_params["auto_current"] = self._safe_read_value(
                p_auto_exp, as_str=True, default="Off"
            )
            available_entries = self._safe_get_attr(p_auto_exp, "available_entries", [])
            exp_params["auto_options"] = [
                entry.name for entry in available_entries if hasattr(entry, "name")
            ]

        p_exp_time = self.pm.find("ExposureTime")
        if p_exp_time:
            exp_params["time_is_writable"] = self._is_property_writable(
                p_exp_time, "ExposureTime"
            )
            if exp_params["auto_current"] != "Off" and exp_params["auto_is_writable"]:
                exp_params["time_is_writable"] = False
            exp_params["time_current_us"] = self._safe_read_value(
                p_exp_time, default=0.0
            )
            exp_params["time_min_us"] = self._safe_get_attr(p_exp_time, "min", 1.0)
            exp_params["time_max_us"] = self._safe_get_attr(
                p_exp_time, "max", 1000000.0
            )
        self.exposure_params_updated.emit(exp_params)
        log.debug(f"Emitted exposure_params_updated: {exp_params}")

        gain_params = {
            "current_db": 0.0,
            "min_db": 0.0,
            "max_db": 48.0,
            "is_writable": False,
        }
        p_gain = self.pm.find("Gain")
        if p_gain:
            gain_params["is_writable"] = self._is_property_writable(p_gain, "Gain")
            gain_params["current_db"] = self._safe_read_value(p_gain, default=0.0)
            gain_params["min_db"] = self._safe_get_attr(p_gain, "min", 0.0)
            gain_params["max_db"] = self._safe_get_attr(p_gain, "max", 48.0)
        self.gain_params_updated.emit(gain_params)
        log.debug(f"Emitted gain_params_updated: {gain_params}")

        fps_params = {
            "current_fps": 0.0,
            "min_fps": 0.1,
            "max_fps": 200.0,
            "is_writable": False,
        }
        p_fps = self.pm.find("AcquisitionFrameRate")
        if p_fps:
            fps_params["is_writable"] = self._is_property_writable(
                p_fps, "AcquisitionFrameRate"
            )
            fps_params["current_fps"] = self._safe_read_value(p_fps, default=0.0)
            fps_params["min_fps"] = self._safe_get_attr(p_fps, "min", 0.1)
            fps_params["max_fps"] = self._safe_get_attr(p_fps, "max", 200.0)
        self.fps_params_updated.emit(fps_params)
        log.debug(f"Emitted fps_params_updated: {fps_params}")

        pf_options = []
        current_pf_str = "N/A"
        p_pf = self.pm.find("PixelFormat")
        if p_pf:
            current_pf_str = self._safe_read_value(p_pf, as_str=True, default="N/A")
            available_pf_entries = self._safe_get_attr(p_pf, "available_entries", [])
            pf_options = [
                entry.name for entry in available_pf_entries if hasattr(entry, "name")
            ]
        self.pixel_format_options_updated.emit(pf_options, current_pf_str)
        log.debug(
            f"Emitted pixel_format_options_updated: {pf_options}, current: {current_pf_str}"
        )

        res_params = {
            "w_min": 0,
            "w_max": 4096,
            "w_curr": 0,
            "w_inc": 1,
            "h_min": 0,
            "h_max": 3000,
            "h_curr": 0,
            "h_inc": 1,
            "w_writable": False,
            "h_writable": False,
        }
        p_width = self.pm.find("Width")
        if p_width:
            res_params["w_writable"] = self._is_property_writable(p_width, "Width")
            res_params["w_curr"] = self._safe_read_value(p_width, default=0)
            res_params["w_min"] = self._safe_get_attr(p_width, "min", 0)
            res_params["w_max"] = self._safe_get_attr(p_width, "max", 4096)
            res_params["w_inc"] = self._safe_get_attr(p_width, "increment", 1)

        p_height = self.pm.find("Height")
        if p_height:
            res_params["h_writable"] = self._is_property_writable(p_height, "Height")
            res_params["h_curr"] = self._safe_read_value(p_height, default=0)
            res_params["h_min"] = self._safe_get_attr(p_height, "min", 0)
            res_params["h_max"] = self._safe_get_attr(p_height, "max", 3000)
            res_params["h_inc"] = self._safe_get_attr(p_height, "increment", 1)
        self.resolution_params_updated.emit(res_params)
        log.debug(f"Emitted resolution_params_updated: {res_params}")

    @pyqtSlot(str)
    def set_exposure_auto(self, mode: str):
        if self.pm:
            if self._attempt_set_property("ExposureAuto", mode, mode):
                self._query_and_emit_camera_parameters()
        else:
            log.warning("ExposureAuto property unavailable or PM not initialized.")

    @pyqtSlot(float)
    def set_exposure_time(self, us: float):
        if self.pm:
            if self._attempt_set_property("ExposureTime", float(us), f"{us}µs"):
                self._query_and_emit_camera_parameters()
        else:
            log.warning("ExposureTime property unavailable or PM not initialized.")

    @pyqtSlot(float)
    def set_gain(self, value_db: float):
        if self.pm:
            if self._attempt_set_property("Gain", float(value_db), f"{value_db}dB"):
                self._query_and_emit_camera_parameters()
        else:
            log.warning("Gain property unavailable or PM not initialized.")

    @pyqtSlot(float)
    def set_fps(self, value_fps: float):
        if self.pm:
            if self._attempt_set_property(
                "AcquisitionFrameRate", float(value_fps), f"{value_fps}FPS"
            ):
                self._query_and_emit_camera_parameters()
        else:
            log.warning(
                "AcquisitionFrameRate property unavailable or PM not initialized."
            )

    @pyqtSlot(str)
    def set_pixel_format(self, format_str: str):
        if self.pm:
            log.info(
                f"Attempting to set PixelFormat to: {format_str}. This may require stream restart if active."
            )
            if self._attempt_set_property("PixelFormat", format_str, format_str):
                self._query_and_emit_camera_parameters()
        else:
            log.warning("PixelFormat property unavailable or PM not initialized.")

    @pyqtSlot(str)
    def set_resolution_from_string(self, res_str: str):
        if self.pm:
            try:
                w_str, h_str = res_str.lower().split("x")
                width = int(w_str)
                height = int(h_str)
                log.info(
                    f"Attempting to set Resolution to: {width}x{height}. This may require stream restart if active."
                )
                width_ok = self._attempt_set_property("Width", width, str(width))
                height_ok = self._attempt_set_property("Height", height, str(height))

                if width_ok or height_ok:
                    self._query_and_emit_camera_parameters()
            except ValueError:
                log.error(f"Could not parse resolution string: {res_str}")
            except Exception as e:
                log.error(f"Error setting resolution from string '{res_str}': {e}")
        else:
            log.warning(
                "Resolution properties (Width/Height) unavailable or PM not initialized."
            )

    @pyqtSlot(int)
    def set_width(self, width: int):
        if self.pm:
            log.info(
                f"Attempting to set Width to: {width}. This may require stream restart if active."
            )
            if self._attempt_set_property("Width", width, str(width)):
                self._query_and_emit_camera_parameters()

    @pyqtSlot(int)
    def set_height(self, height: int):
        if self.pm:
            log.info(
                f"Attempting to set Height to: {height}. This may require stream restart if active."
            )
            if self._attempt_set_property("Height", height, str(height)):
                self._query_and_emit_camera_parameters()

    def run(self):
        try:
            devices = ic4.DeviceEnum.devices()
            if not devices:
                raise RuntimeError("No IC4 devices found.")
            target_device = None
            if self.device_identifier:
                for d in devices:
                    dev_serial = getattr(d, "serial", "")
                    dev_unique_name = getattr(d, "unique_name", "")
                    dev_model_name = getattr(d, "model_name", "")
                    if self.device_identifier in (
                        dev_serial,
                        dev_unique_name,
                        dev_model_name,
                    ):
                        target_device = d
                        break
                if not target_device:
                    raise RuntimeError(f"Camera '{self.device_identifier}' not found.")
            else:
                target_device = devices[0]

            self.grabber = ic4.Grabber()
            self.grabber.device_open(target_device)
            self.pm = self.grabber.device_property_map
            log.info(
                f"Device '{target_device.model_name if hasattr(target_device, 'model_name') else 'N/A'}' opened. PropertyMap acquired."
            )

            initial_configs = [
                ("PixelFormat", "Mono8"),
                ("AcquisitionMode", "Continuous"),
                ("TriggerMode", "Off"),
                # ("AcquisitionFrameRateEnable", True), # Not all cameras have this specific property
                ("AcquisitionFrameRate", self.initial_target_fps),
            ]
            for prop_name, val_to_set in initial_configs:
                self._attempt_set_property(prop_name, val_to_set)  # Will log if fails

            self._query_and_emit_camera_parameters()

            self.sink = ic4.QueueSink(listener=self.sink_listener)
            self.grabber.stream_setup(self.sink)
            log.info("Stream setup complete.")

            if not self.grabber.is_acquisition_active:
                self.grabber.acquisition_start()
                log.info("Acquisition started.")

            while not self._stop_requested:
                try:
                    # Corrected: use positional argument for timeout
                    buf = self.sink.pop_output_buffer(100)

                    if not buf:
                        continue

                    if not buf.is_valid:
                        log.warning("Received invalid buffer from sink.")
                        buf.release()
                        QThread.msleep(5)  # Small pause if invalid buffer spam
                        continue

                    arr = buf.numpy_wrap()
                    img_format = QImage.Format_Invalid
                    if arr.ndim == 2:
                        img_format = QImage.Format_Grayscale8
                    elif arr.ndim == 3 and arr.shape[2] == 3:
                        img_format = QImage.Format_BGR888
                    elif arr.ndim == 3 and arr.shape[2] == 1:
                        img_format = QImage.Format_Grayscale8
                        arr = arr.squeeze(axis=2)

                    if img_format != QImage.Format_Invalid:
                        qimg = QImage(
                            arr.data,
                            arr.shape[1],
                            arr.shape[0],
                            arr.strides[0],
                            img_format,
                        )
                        self.frame_ready.emit(qimg.copy(), arr.copy())
                    else:
                        log.warning(
                            f"Unsupported numpy array shape for QImage: {arr.shape}"
                        )
                    buf.release()
                except ic4.IC4Exception as e:
                    if (
                        e.code == ic4.ErrorCode.Timeout
                        or e.code == ic4.ErrorCode.NoData
                    ):
                        continue
                    log.error(
                        f"IC4Exception in frame processing loop: {e} (Code: {e.code})"
                    )
                    self.camera_error.emit(str(e), str(e.code))
                    break
                except Exception as e_loop:
                    log.exception(f"Generic error in frame processing loop: {e_loop}")
                    self.camera_error.emit(str(e_loop), type(e_loop).__name__)
                    break
            log.info("Exited frame processing loop.")
        except RuntimeError as e_rt:
            log.error(f"RuntimeError during SDKCameraThread execution: {e_rt}")
            self.camera_error.emit(str(e_rt), type(e_rt).__name__)
        except ic4.IC4Exception as e_ic4_setup:
            log.error(
                f"IC4Exception during SDKCameraThread setup: {e_ic4_setup} (Code: {e_ic4_setup.code})"
            )
            self.camera_error.emit(str(e_ic4_setup), str(e_ic4_setup.code))
        except Exception as e_setup:
            log.exception(f"Unexpected error during SDKCameraThread setup: {e_setup}")
            self.camera_error.emit(str(e_setup), type(e_setup).__name__)
        finally:
            log.info("SDKCameraThread.run() is finishing. Cleaning up...")
            try:
                if self.grabber:
                    if self.grabber.is_acquisition_active:
                        log.info("Stopping acquisition...")
                        self.grabber.acquisition_stop()
                    if self.grabber.is_device_open:
                        log.info("Closing device...")
                        self.grabber.device_close()
            except Exception as e_cleanup:
                log.error(f"Error during grabber cleanup: {e_cleanup}")

            self.grabber = None
            self.pm = None
            log.info("SDKCameraThread cleanup complete. Thread finished.")

    def stop(self):
        log.info(f"Stop requested for SDKCameraThread ({self.device_identifier}).")
        self._stop_requested = True
        if self.isRunning():
            if not self.wait(3000):
                log.warning(
                    "SDKCameraThread did not stop in time (3s), attempting terminate."
                )
                self.terminate()
                if not self.wait(500):
                    log.error("SDKCameraThread failed to terminate.")
            else:
                log.info("SDKCameraThread stopped gracefully.")
        else:
            log.info("SDKCameraThread was not running when stop was called.")
