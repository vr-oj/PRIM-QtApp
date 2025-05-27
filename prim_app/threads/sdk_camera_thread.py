# PRIM-QTAPP/prim_app/threads/sdk_camera_thread.py
import re
import numpy as np
import logging
import imagingcontrol4 as ic4
from utils.utils import to_prop_name
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


def read_current(pm, prop_id_obj_or_name):
    """
    Try each typed getter until one succeeds, return the first value or None.
    `prop_id_obj_or_name` can be a PropId object or its string name.
    """
    target_prop = prop_id_obj_or_name
    if isinstance(prop_id_obj_or_name, str):  # If string name is passed
        try:
            target_prop = pm.find(prop_id_obj_or_name)
            if target_prop is None:  # Check if find returned None
                log.debug(f"Property '{prop_id_obj_or_name}' not found by pm.find().")
                return None
        except ic4.IC4Exception as e:  # find can also raise
            log.debug(f"Error finding property '{prop_id_obj_or_name}': {e}")
            return None

    # Now target_prop should be a Property object or a direct PropId object
    # Some pm.get_value_TYPE methods might accept PropId object directly too.
    try:
        return pm.get_value_int(target_prop)
    except ic4.IC4Exception:
        pass
    try:
        return pm.get_value_float(target_prop)
    except ic4.IC4Exception:
        pass
    try:
        return pm.get_value_str(target_prop)
    except ic4.IC4Exception:
        pass
    try:
        return pm.get_value_bool(target_prop)
    except ic4.IC4Exception:
        pass

    log.debug(
        f"Could not read value for property via standard getters: {prop_id_obj_or_name}"
    )
    return None


class SDKCameraThread(QThread):
    frame_ready = pyqtSignal(QImage, object)
    resolutions_updated = pyqtSignal(list)
    pixel_formats_updated = pyqtSignal(list)
    fps_range_updated = pyqtSignal(float, float)
    exposure_range_updated = pyqtSignal(float, float)
    gain_range_updated = pyqtSignal(float, float)
    auto_exposure_updated = pyqtSignal(bool)
    properties_updated = pyqtSignal(dict)
    camera_error = pyqtSignal(str, str)

    _propid_map = {
        name: getattr(ic4.PropId, name)
        for name in dir(ic4.PropId)
        if not name.startswith("_") and not callable(getattr(ic4.PropId, name))
    }

    def __init__(self, device_name=None, fps=10, parent=None):
        super().__init__(parent)
        self.device_identifier = device_name
        self.target_fps = float(fps)
        self._stop_requested = False
        self.grabber = None
        self.pm = None
        log.info(
            f"SDKCameraThread initialized for device_identifier: '{self.device_identifier}', target_fps: {self.target_fps}"
        )

    def apply_node_settings(self, settings: dict):
        if not self.grabber or not self.pm:
            log.warning("Apply_node_settings called but grabber or pm not initialized.")
            return

        applied = {}
        for key_camel_case, val in settings.items():
            pid_name_upper_snake = to_prop_name(key_camel_case)
            # Use the string name directly with pm.find or pm.set_value if it accepts names
            # Or use the PropId object from _propid_map if set_value requires PropId objects
            prop_id_obj = self._propid_map.get(pid_name_upper_snake)
            target_for_set_value = (
                prop_id_obj if prop_id_obj else pid_name_upper_snake
            )  # Fallback to name if obj not in map

            if not prop_id_obj:  # Log if not in map, but still try with string name
                log.warning(
                    f"PropId object for '{pid_name_upper_snake}' not in _propid_map. Will attempt to set by string name."
                )

            try:
                log.debug(
                    f"Attempting to set {pid_name_upper_snake} to {val} (type: {type(val)}) using identifier: {target_for_set_value}"
                )

                if pid_name_upper_snake == "PIXEL_FORMAT" and isinstance(val, str):
                    pixel_format_member = getattr(ic4.PixelFormat, val, None)
                    if pixel_format_member is not None:
                        self.pm.set_value(target_for_set_value, pixel_format_member)
                    else:
                        self.pm.set_value(target_for_set_value, val)
                elif pid_name_upper_snake == "EXPOSURE_AUTO" and isinstance(val, str):
                    self.pm.set_value(target_for_set_value, val)
                else:
                    self.pm.set_value(target_for_set_value, val)

                actual = read_current(
                    self.pm, target_for_set_value
                )  # Read back using same identifier
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
                    current_serial = (
                        dev_info.serial if hasattr(dev_info, "serial") else ""
                    )
                    current_unique_name = (
                        dev_info.unique_name if hasattr(dev_info, "unique_name") else ""
                    )
                    current_model_name = (
                        dev_info.model_name if hasattr(dev_info, "model_name") else ""
                    )
                    if (
                        self.device_identifier == current_serial
                        or self.device_identifier == current_unique_name
                        or (
                            not current_serial
                            and not current_unique_name
                            and self.device_identifier == current_model_name
                        )
                    ):
                        target_device_info = dev_info
                        log.info(
                            f"Found matching device in SDKCameraThread: Model='{current_model_name}', Serial='{current_serial}', UniqueName='{current_unique_name}'"
                        )
                        break
                if not target_device_info:
                    err_msg = f"Camera with identifier '{self.device_identifier}' not found in SDKCameraThread."
                    log.error(err_msg)
                    raise RuntimeError(err_msg)
            elif all_devices:
                target_device_info = all_devices[0]
                log.info(
                    f"No specific device identifier provided to SDKCameraThread, using first available: {target_device_info.model_name}"
                )
            else:
                raise RuntimeError("No devices and no identifier specified.")

            log.info(
                f"SDKCameraThread attempting to open: {target_device_info.model_name} (Serial: {target_device_info.serial if hasattr(target_device_info, 'serial') else 'N/A'})"
            )
            self.grabber = ic4.Grabber()
            self.grabber.device_open(target_device_info)
            self.pm = self.grabber.device_property_map
            log.info(
                f"Device {target_device_info.model_name} opened successfully in SDKCameraThread. PropertyMap acquired."
            )

            # Function to get property ranges and current values
            def query_property_details(
                prop_string_name_upper_snake,
                range_signal_emitter=None,
                current_value_signal_emitter=None,
                current_value_signal_key=None,
            ):
                # PropId object is no longer strictly needed if pm.find() uses string name
                # prop_id_obj = self._propid_map.get(prop_string_name_upper_snake)
                # if not prop_id_obj:
                #     log.warning(f"PropId for '{prop_string_name_upper_snake}' not in _propid_map for query.")
                #     return None # Return None for current value if property cannot be identified

                current_value = None
                try:
                    prop_item = self.pm.find(
                        prop_string_name_upper_snake
                    )  # Find property by its string name
                    if prop_item is None:
                        log.warning(
                            f"Property '{prop_string_name_upper_snake}' not found in PropertyMap."
                        )
                        return None  # Current value is None

                    # Get current value using the generic read_current or specific typed value from prop_item
                    current_value = (
                        prop_item.value
                    )  # if .value gives the actual value directly
                    # otherwise use read_current(self.pm, prop_string_name_upper_snake)
                    if current_value is None:  # Fallback if .value isn't right
                        current_value = read_current(
                            self.pm, prop_string_name_upper_snake
                        )

                    if current_value_signal_emitter and current_value_signal_key:
                        # For ExposureAuto, we need to convert string "Off"/"Continuous" to bool
                        if (
                            prop_string_name_upper_snake == "EXPOSURE_AUTO"
                            and isinstance(current_value, str)
                        ):
                            current_value_signal_emitter.emit(
                                current_value.lower() != "off"
                            )
                        else:  # For others, assume current_value_signal_emitter handles a dict
                            current_value_signal_emitter.emit(
                                {current_value_signal_key: current_value}
                            )
                    elif (
                        current_value_signal_emitter
                    ):  # If emitter takes value directly (e.g. ExposureAuto)
                        if (
                            prop_string_name_upper_snake == "EXPOSURE_AUTO"
                            and isinstance(current_value, str)
                        ):
                            current_value_signal_emitter.emit(
                                current_value.lower() != "off"
                            )
                        # else: current_value_signal_emitter.emit(current_value) # Not used currently

                    # Get Min/Max for Integer/Float types
                    if (
                        prop_item.type == ic4.PropertyType.INTEGER
                        or prop_item.type == ic4.PropertyType.FLOAT
                    ):
                        min_val = prop_item.min
                        max_val = prop_item.max
                        # inc_val = prop_item.inc # Or .increment
                        log.debug(
                            f"{prop_string_name_upper_snake} (Type: {prop_item.type}): Val={current_value}, Range=[{min_val}-{max_val}]"
                        )
                        if range_signal_emitter:
                            range_signal_emitter.emit(min_val, max_val)
                    elif prop_item.type == ic4.PropertyType.ENUMERATION:
                        options = list(prop_item.available_enumeration_names)
                        log.debug(
                            f"{prop_string_name_upper_snake} (Enum): Val='{current_value}', Options={options}"
                        )
                        if (
                            range_signal_emitter
                        ):  # Assuming range_signal_emitter here is for options list
                            range_signal_emitter.emit(
                                options
                            )  # e.g., self.pixel_formats_updated
                    else:
                        log.debug(
                            f"{prop_string_name_upper_snake} (Type: {prop_item.type}): Val={current_value}"
                        )

                except ic4.IC4Exception as e:
                    log.warning(
                        f"IC4Exception querying details for {prop_string_name_upper_snake}: {e} (Code: {e.code})"
                    )
                except (
                    AttributeError
                ) as e_attr:  # Catch AttributeErrors if .min, .max, .type, .value are not on prop_item
                    log.warning(
                        f"AttributeError querying details for {prop_string_name_upper_snake} (likely type {prop_item.type if 'prop_item' in locals() else 'unknown'}): {e_attr}"
                    )
                except Exception as e_gen:
                    log.warning(
                        f"Generic exception querying details for {prop_string_name_upper_snake}: {e_gen}"
                    )
                return current_value

            # Query initial property states and ranges
            query_property_details(
                "ACQUISITION_FRAME_RATE",
                self.fps_range_updated,
                self.properties_updated,
                "ACQUISITION_FRAME_RATE",
            )
            query_property_details(
                "EXPOSURE_TIME",
                self.exposure_range_updated,
                self.properties_updated,
                "EXPOSURE_TIME",
            )
            query_property_details(
                "GAIN", self.gain_range_updated, self.properties_updated, "GAIN"
            )
            query_property_details(
                "EXPOSURE_AUTO", self.auto_exposure_updated
            )  # Emits bool directly
            query_property_details(
                "PIXEL_FORMAT",
                self.pixel_formats_updated,
                self.properties_updated,
                "PIXEL_FORMAT",
            )
            query_property_details(
                "WIDTH", None, self.properties_updated, "WIDTH"
            )  # No specific range signal for Width/Height now
            query_property_details("HEIGHT", None, self.properties_updated, "HEIGHT")

            # Try to set initial FPS (passed to __init__)
            try:
                # prop_id_fps = self._propid_map.get("ACQUISITION_FRAME_RATE") # We can use string name now
                prop_fps = self.pm.find("ACQUISITION_FRAME_RATE")
                if prop_fps and prop_fps.is_writable:  # Check if writable
                    self.pm.set_value("ACQUISITION_FRAME_RATE", self.target_fps)
                    log.info(f"SDKCameraThread: Set initial FPS to {self.target_fps}")
                    # Update properties_updated signal with this new value
                    self.properties_updated.emit(
                        {"ACQUISITION_FRAME_RATE": self.target_fps}
                    )
            except ic4.IC4Exception as e:
                log.warning(
                    f"SDKCameraThread: Could not set initial FPS to {self.target_fps}: {e}"
                )

            # Emit all initial properties collected (some might have been emitted by query_property_details)
            # This is slightly redundant if properties_updated was called inside query_property_details,
            # but can be a consolidated update. Let's rely on individual emits for now.
            # log.info(f"SDKCameraThread: Emitting consolidated initial properties: {self.properties_updated_cache}")
            # self.properties_updated.emit(self.properties_updated_cache.copy())

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

                    q_image_format = QImage.Format_Grayscale8
                    if arr.ndim == 3 and arr.shape[2] == 3:
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
                    log.exception(
                        f"Generic exception in SDKCameraThread acquisition loop: {e_loop}"
                    )  # Use .exception
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
        except Exception as ex_outer:
            log.exception(
                f"Outer unhandled exception in SDKCameraThread.run: {ex_outer}"
            )
            self.camera_error.emit(
                str(ex_outer), getattr(ex_outer, "__class__", type(ex_outer)).__name__
            )
        finally:
            log.debug("SDKCameraThread.run() entering finally block for cleanup.")
            if self.grabber:
                try:
                    # --- CORRECTED BOOLEAN PROPERTY ACCESS ---
                    if self.grabber.is_acquisition_active:
                        log.debug("SDKCameraThread: Stopping acquisition...")
                        self.grabber.acquisition_stop()
                except Exception as e_acq_stop:
                    log.error(f"Exception during acquisition_stop: {e_acq_stop}")
                try:
                    if self.grabber.is_device_open:
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
