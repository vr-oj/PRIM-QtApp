# PRIM-QTAPP/prim_app/threads/sdk_camera_thread.py
import re
import numpy as np
import logging
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


def to_prop_name(key: str) -> str:
    """Convert CamelCase or mixed to UPPER_SNAKE_CASE to match PropId names."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", key)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).upper()


def read_current(pm, pid):
    """
    Try each typed getter until one succeeds, return the first value or None.
    """
    try:
        return pm.get_value_int(pid)
    except ic4.IC4Exception:
        pass
    try:
        return pm.get_value_float(pid)
    except ic4.IC4Exception:
        pass
    try:
        return pm.get_value_str(pid)
    except ic4.IC4Exception:
        pass
    try:
        return pm.get_value_bool(pid)
    except ic4.IC4Exception:
        pass

    log.debug(f"Could not read value for PID via standard getters: {pid}")
    return None


class SDKCameraThread(QThread):
    frame_ready = pyqtSignal(QImage, object)
    resolutions_updated = pyqtSignal(
        list
    )  # May not be used if Width/Height are main props
    pixel_formats_updated = pyqtSignal(list)
    fps_range_updated = pyqtSignal(float, float)
    exposure_range_updated = pyqtSignal(float, float)
    gain_range_updated = pyqtSignal(float, float)
    auto_exposure_updated = pyqtSignal(bool)
    properties_updated = pyqtSignal(dict)  # Emits dict with UPPER_SNAKE_CASE keys
    camera_error = pyqtSignal(str, str)

    _propid_map = {
        name: getattr(ic4.PropId, name)
        for name in dir(ic4.PropId)
        if not name.startswith("_") and not callable(getattr(ic4.PropId, name))
    }

    def __init__(
        self, device_name=None, fps=10, parent=None
    ):  # device_name is expected to be serial or unique_name
        super().__init__(parent)
        self.device_identifier = device_name
        self.target_fps = float(fps)
        self._stop_requested = False
        self.grabber = None
        self.pm = None
        log.info(
            f"SDKCameraThread initialized for device_identifier: '{self.device_identifier}', target_fps: {self.target_fps}"
        )

    def apply_node_settings(
        self, settings: dict
    ):  # Expects CamelCase keys from UI/config
        if not self.grabber or not self.pm:
            log.warning("Apply_node_settings called but grabber or pm not initialized.")
            return

        applied = {}
        for key_camel_case, val in settings.items():
            pid_name_upper_snake = to_prop_name(key_camel_case)
            prop_id_obj = self._propid_map.get(pid_name_upper_snake)

            if not prop_id_obj:
                log.error(
                    f"Unknown property key: '{key_camel_case}' (maps to '{pid_name_upper_snake}') in _propid_map."
                )
                self.camera_error.emit(f"Unknown property '{key_camel_case}'", "")
                continue
            try:
                log.debug(
                    f"Attempting to set {pid_name_upper_snake} to {val} (type: {type(val)}) using PropID: {prop_id_obj}"
                )

                if pid_name_upper_snake == "PIXEL_FORMAT" and isinstance(val, str):
                    pixel_format_member = getattr(
                        ic4.PixelFormat, val, None
                    )  # e.g., ic4.PixelFormat.Mono8
                    if pixel_format_member is not None:
                        log.debug(
                            f"Setting PixelFormat using enum member: {pixel_format_member}"
                        )
                        self.pm.set_value(prop_id_obj, pixel_format_member)
                    else:  # Fallback to string if direct enum not found (less likely to work)
                        log.warning(
                            f"PixelFormat enum member for '{val}' not found, trying string directly."
                        )
                        self.pm.set_value(prop_id_obj, val)
                elif pid_name_upper_snake == "EXPOSURE_AUTO" and isinstance(
                    val, str
                ):  # e.g. "Off", "Continuous"
                    self.pm.set_value(prop_id_obj, val)
                else:  # General case for int, float, bool
                    self.pm.set_value(prop_id_obj, val)

                actual = read_current(self.pm, prop_id_obj)
                log.info(
                    f"Successfully set {pid_name_upper_snake} to {val}, read back: {actual}"
                )
                applied[pid_name_upper_snake] = actual
            except ic4.IC4Exception as e:
                log.error(
                    f"IC4Exception setting {pid_name_upper_snake} to {val}: {e} (Code: {e.code})"
                )
                self.camera_error.emit(
                    f"Failed to set {pid_name_upper_snake} to {val}: {e}", str(e.code)
                )
            except Exception as e_gen:
                log.error(
                    f"Generic Exception setting {pid_name_upper_snake} to {val}: {e_gen}"
                )
                self.camera_error.emit(
                    f"Failed to set {pid_name_upper_snake} to {val}: {e_gen}", ""
                )
        if applied:
            self.properties_updated.emit(applied)

    def run(self):
        try:
            all_devices = ic4.DeviceEnum.devices()
            if not all_devices:
                log.error(
                    "No camera devices found by ic4.DeviceEnum in SDKCameraThread."
                )
                raise RuntimeError("No camera devices found")

            target_device_info = None
            if self.device_identifier:
                for dev_info in all_devices:
                    # --- CORRECTED DeviceInfo ACCESS ---
                    current_serial = (
                        dev_info.serial if hasattr(dev_info, "serial") else ""
                    )
                    current_unique_name = (
                        dev_info.unique_name if hasattr(dev_info, "unique_name") else ""
                    )
                    current_model_name = (
                        dev_info.model_name if hasattr(dev_info, "model_name") else ""
                    )
                    # --- END CORRECTION ---

                    if (
                        self.device_identifier == current_serial
                        or self.device_identifier == current_unique_name
                        or (
                            not current_serial
                            and not current_unique_name
                            and self.device_identifier == current_model_name
                        )
                    ):  # Fallback for devices without serial/unique_id
                        target_device_info = dev_info
                        log.info(
                            f"Found matching device in SDKCameraThread: Model='{current_model_name}', Serial='{current_serial}', UniqueName='{current_unique_name}'"
                        )
                        break
                if not target_device_info:
                    err_msg = f"Camera with identifier '{self.device_identifier}' not found in SDKCameraThread."
                    log.error(err_msg)
                    raise RuntimeError(err_msg)
            elif all_devices:  # If no identifier, take the first one
                target_device_info = all_devices[0]
                log.info(
                    f"No specific device identifier provided to SDKCameraThread, using first available: {target_device_info.model_name}"
                )
            else:  # Should be caught by `if not all_devices`
                raise RuntimeError("No devices and no identifier specified.")

            log.info(
                f"SDKCameraThread attempting to open: {target_device_info.model_name} (Serial: {target_device_info.serial if hasattr(target_device_info, 'serial') else 'N/A'})"
            )
            self.grabber = ic4.Grabber()
            self.grabber.device_open(target_device_info)
            self.pm = self.grabber.device_property_map
            log.info(
                f"Device {target_device_info.model_name} opened successfully in SDKCameraThread."
            )

            # Initial property querying and UI updates
            def get_prop_range_and_update(prop_string_name_upper_snake, signal_emitter):
                prop_id_obj = self._propid_map.get(prop_string_name_upper_snake)
                if not prop_id_obj:
                    log.warning(
                        f"PropId for '{prop_string_name_upper_snake}' not in _propid_map."
                    )
                    return
                try:
                    min_val = self.pm.get_min(prop_id_obj)
                    max_val = self.pm.get_max(prop_id_obj)
                    log.debug(
                        f"{prop_string_name_upper_snake} range: {min_val} - {max_val}"
                    )
                    if signal_emitter:
                        signal_emitter.emit(min_val, max_val)
                except ic4.IC4Exception as e:
                    log.warning(
                        f"{prop_string_name_upper_snake} range not available: {e} (Code: {e.code})"
                    )

            get_prop_range_and_update("ACQUISITION_FRAME_RATE", self.fps_range_updated)
            get_prop_range_and_update("EXPOSURE_TIME", self.exposure_range_updated)
            get_prop_range_and_update("GAIN", self.gain_range_updated)

            try:  # ExposureAuto
                prop_id_obj = self._propid_map.get("EXPOSURE_AUTO")
                if prop_id_obj:
                    auto_val_str = self.pm.get_value_str(prop_id_obj)
                    self.auto_exposure_updated.emit(auto_val_str.lower() != "off")
            except ic4.IC4Exception as e:
                log.warning(f"Could not read ExposureAuto: {e}. Assuming Off/False.")
                self.auto_exposure_updated.emit(False)

            # Try to set initial FPS (passed to __init__)
            try:
                prop_id_fps = self._propid_map.get("ACQUISITION_FRAME_RATE")
                if prop_id_fps and self.pm.is_writable(prop_id_fps):
                    self.pm.set_value(prop_id_fps, self.target_fps)
                    log.info(f"SDKCameraThread: Set initial FPS to {self.target_fps}")
            except ic4.IC4Exception as e:
                log.warning(
                    f"SDKCameraThread: Could not set initial FPS to {self.target_fps}: {e}"
                )

            # Emit all initial current property values that the UI might care about
            initial_props_to_read = [
                "EXPOSURE_TIME",
                "GAIN",
                "PIXEL_FORMAT",
                "ACQUISITION_FRAME_RATE",
                "WIDTH",
                "HEIGHT",
                "EXPOSURE_AUTO",
            ]
            current_props_state = {}
            for prop_name_upper_snake in initial_props_to_read:
                prop_id_obj = self._propid_map.get(prop_name_upper_snake)
                if prop_id_obj:
                    val = read_current(self.pm, prop_id_obj)
                    if val is not None:
                        current_props_state[prop_name_upper_snake] = val
            if current_props_state:
                log.info(
                    f"SDKCameraThread: Initial live properties read: {current_props_state}"
                )
                self.properties_updated.emit(current_props_state)

            # Setup stream
            sink = ic4.QueueSink()
            log.debug("SDKCameraThread: Setting up stream...")
            self.grabber.stream_setup(
                sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            log.info("SDKCameraThread: Stream setup complete, acquisition active.")

            while not self._stop_requested:
                try:
                    buf = sink.pop_output_buffer(1000)
                    if not buf:
                        continue
                    arr = buf.numpy_wrap()

                    # Determine QImage format based on actual pixel format from camera
                    # This is a simplified version; robust handling needs current_props_state["PIXEL_FORMAT"]
                    q_image_format = QImage.Format_Grayscale8  # Default
                    if arr.ndim == 3 and arr.shape[2] == 3:  # Assuming BGR
                        q_image_format = QImage.Format_BGR888
                    elif arr.ndim == 2 or (arr.ndim == 3 and arr.shape[2] == 1):
                        q_image_format = QImage.Format_Grayscale8
                    else:
                        log.warning(
                            f"Unsupported numpy array shape for QImage: {arr.shape}"
                        )
                        buf.release()
                        continue

                    final_arr = (
                        arr[..., 0]
                        if arr.ndim == 3 and q_image_format == QImage.Format_Grayscale8
                        else arr
                    )
                    q_image = QImage(
                        final_arr.data,
                        final_arr.shape[1],
                        final_arr.shape[0],
                        final_arr.strides[0],
                        q_image_format,
                    )
                    self.frame_ready.emit(q_image.copy(), arr.copy())
                    buf.release()
                except ic4.IC4Exception as e:
                    if e.code == ic4.ErrorCode.Timeout:
                        continue
                    log.error(
                        f"IC4Exception in SDKCameraThread acquisition loop: {e} (Code: {e.code})"
                    )
                    self.camera_error.emit(str(e), str(e.code))
                    break
                except Exception as e_loop:
                    log.error(
                        f"Generic exception in SDKCameraThread acquisition loop: {e_loop}"
                    )
                    self.camera_error.emit(str(e_loop), "")
                    break
            log.info("SDKCameraThread: Exited acquisition loop.")

        except RuntimeError as e_rt:
            log.error(f"RuntimeError in SDKCameraThread.run: {e_rt}")
            self.camera_error.emit(str(e_rt), "RUNTIME_ERROR")
        except ic4.IC4Exception as e_ic4_setup:
            log.error(
                f"IC4Exception during setup in SDKCameraThread.run: {e_ic4_setup} (Code: {e_ic4_setup.code})"
            )
            self.camera_error.emit(str(e_ic4_setup), str(e_ic4_setup.code))
        except Exception as ex_outer:  # Catch-all for unexpected errors during setup
            log.exception(
                f"Outer unhandled exception in SDKCameraThread.run: {ex_outer}"
            )  # Use .exception for traceback
            self.camera_error.emit(
                str(ex_outer), getattr(ex_outer, "__class__", type(ex_outer)).__name__
            )
        finally:
            log.debug("SDKCameraThread.run() entering finally block for cleanup.")
            if self.grabber:
                try:
                    if self.grabber.is_acquisition_active():
                        log.debug("SDKCameraThread: Stopping acquisition...")
                        self.grabber.acquisition_stop()
                except Exception as e_acq_stop:
                    log.error(f"Exception during acquisition_stop: {e_acq_stop}")
                try:
                    if self.grabber.is_device_open():
                        log.debug("SDKCameraThread: Closing device...")
                        self.grabber.device_close()
                except Exception as e_dev_close:
                    log.error(f"Exception during device_close: {e_dev_close}")
            self.grabber = None
            self.pm = None
            log.info("SDKCameraThread finished and cleaned up.")

    def stop(self):
        log.info(f"SDKCameraThread.stop() called for device {self.device_identifier}.")
        self._stop_requested = True
        if self.isRunning():
            if not self.wait(3000):
                log.warning(
                    f"SDKCameraThread for {self.device_identifier} did not exit gracefully, terminating."
                )
                self.terminate()
                self.wait(500)
        log.info(
            f"SDKCameraThread.stop() completed for device {self.device_identifier}."
        )
