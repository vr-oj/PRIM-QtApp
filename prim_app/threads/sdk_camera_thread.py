# PRIM-QTAPP/prim_app/threads/sdk_camera_thread.py
import re
import numpy as np
import logging
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

from utils.utils import to_prop_name

log = logging.getLogger(__name__)


class MinimalSinkListener(ic4.QueueSinkListener):
    def __init__(self, owner_name="DefaultListener"):
        super().__init__()
        self.owner_name = owner_name
        log.debug(f"MinimalSinkListener '{self.owner_name}' created.")

    def frame_ready(self, sink: ic4.QueueSink, buffer: ic4.ImageBuffer, userdata: any):
        pass

    def frames_queued(self, sink: ic4.QueueSink, userdata: any):
        pass

    def sink_connected(
        self, sink: ic4.QueueSink, image_type_proposed: ic4.ImageType, userdata: any
    ) -> bool:
        log.debug(
            f"Listener '{self.owner_name}': Sink connected. Grabber proposed ImageType: {image_type_proposed}. Accepting."
        )
        return True

    # CORRECTED: Added userdata argument
    def sink_disconnected(self, sink: ic4.QueueSink, userdata: any):
        log.debug(f"Listener '{self.owner_name}': Sink disconnected.")
        pass

    def sink_property_changed(
        self, sink: ic4.QueueSink, property_name: str, userdata: any
    ):
        pass


def read_current(pm: ic4.PropertyMap, prop_identifier):
    if hasattr(prop_identifier, "value") and not isinstance(
        prop_identifier, (str, ic4.PropId)
    ):
        try:
            return prop_identifier.value
        except Exception as e_prop_val:
            log.debug(f"Could not read .value from Property object: {e_prop_val}")
    target_for_get = prop_identifier
    try:
        return pm.get_value_int(target_for_get)
    except ic4.IC4Exception:
        pass
    try:
        return pm.get_value_float(target_for_get)
    except ic4.IC4Exception:
        pass
    try:
        return pm.get_value_str(target_for_get)
    except ic4.IC4Exception:
        pass
    try:
        return pm.get_value_bool(target_for_get)
    except ic4.IC4Exception:
        pass
    log.debug(
        f"Could not read current value for property via standard getters: {prop_identifier}"
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
        name_upper_snake: getattr(ic4.PropId, name_upper_snake)
        for name_upper_snake in dir(ic4.PropId)
        if not name_upper_snake.startswith("_")
        and not callable(getattr(ic4.PropId, name_upper_snake))
        and isinstance(getattr(ic4.PropId, name_upper_snake), ic4.PropId)
    }

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
            f"SDKCameraThread initialized for device_identifier: '{self.device_identifier}', target_fps: {self.target_fps}"
        )

    def apply_node_settings(self, settings: dict):
        if not self.grabber or not self.pm:
            log.warning("Apply_node_settings called but grabber or pm not initialized.")
            return

        applied = {}
        for key_camel_case, val in settings.items():
            pid_name_upper_snake = to_prop_name(key_camel_case)
            prop_id_obj = self._propid_map.get(pid_name_upper_snake)

            if not prop_id_obj:
                log.warning(
                    f"PropId object for '{key_camel_case}' (maps to '{pid_name_upper_snake}') not found in _propid_map. Trying to set by string name '{key_camel_case}'."
                )
                target_for_set_value = key_camel_case
            else:
                target_for_set_value = prop_id_obj

            try:
                log.debug(
                    f"Attempting to set GenICam Feature (using identifier: {target_for_set_value}) to {val} (type: {type(val)})"
                )

                if key_camel_case == "PixelFormat" and isinstance(val, str):
                    pixel_format_member = getattr(ic4.PixelFormat, val, None)
                    if pixel_format_member is not None:
                        self.pm.set_value(target_for_set_value, pixel_format_member)
                    else:
                        self.pm.set_value(target_for_set_value, val)
                elif key_camel_case == "ExposureAuto" and isinstance(val, str):
                    self.pm.set_value(target_for_set_value, val)
                else:
                    self.pm.set_value(target_for_set_value, val)

                current_val_after_set = read_current(self.pm, target_for_set_value)
                log.info(
                    f"Successfully set feature for key '{key_camel_case}' to {val}, read back: {current_val_after_set}"
                )
                applied[pid_name_upper_snake] = current_val_after_set
            except ic4.IC4Exception as e:
                log.error(
                    f"IC4Exception setting feature for key '{key_camel_case}' to {val}: {e} (Code: {e.code})"
                )
                self.camera_error.emit(
                    f"Failed to set '{key_camel_case}' to {val}: {e}", str(e.code)
                )
            except Exception as e_gen:
                log.exception(
                    f"Generic Exception setting feature for key '{key_camel_case}' to {val}: {e_gen}"
                )
                self.camera_error.emit(
                    f"Failed to set '{key_camel_case}' to {val}: {e_gen}", ""
                )
        if applied:
            self.properties_updated.emit(applied)

    def run(self):
        try:
            all_devices = ic4.DeviceEnum.devices()
            if not all_devices:
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
                    current_model_name = dev_info.model_name
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
                        break
                if not target_device_info:
                    raise RuntimeError(
                        f"Camera with identifier '{self.device_identifier}' not found."
                    )
            elif all_devices:
                target_device_info = all_devices[0]
            else:
                raise RuntimeError("No devices and no identifier specified.")

            log.info(
                f"SDKCameraThread attempting to open: {target_device_info.model_name} (Identifier used: {self.device_identifier})"
            )
            self.grabber = ic4.Grabber()
            self.grabber.device_open(target_device_info)
            self.pm = self.grabber.device_property_map
            log.info(
                f"Device {target_device_info.model_name} opened. PropertyMap acquired."
            )

            def query_property_details(
                feature_name_camel_case,
                range_signal_emitter=None,
                current_val_direct_emitter=None,
                properties_update_dict_emitter=None,
            ):
                current_value = None
                try:
                    prop_item = self.pm.find(feature_name_camel_case)
                    if prop_item is None:
                        log.warning(
                            f"GenICam Feature '{feature_name_camel_case}' not found in PropertyMap via find()."
                        )
                        prop_id_obj = self._propid_map.get(
                            to_prop_name(feature_name_camel_case)
                        )
                        if prop_id_obj:
                            current_value = read_current(self.pm, prop_id_obj)
                            if current_value is None:
                                log.warning(
                                    f"Still could not read current value for {feature_name_camel_case} using PropId object."
                                )
                            else:
                                log.debug(
                                    f"Read current value for {feature_name_camel_case} using PropId object directly: {current_value}"
                                )
                        else:
                            return None
                    else:
                        current_value = prop_item.value
                        log.debug(
                            f"Property '{feature_name_camel_case}': Type={prop_item.type}, Value={current_value}"
                        )

                        if (
                            prop_item.type == ic4.PropertyType.INTEGER
                            or prop_item.type == ic4.PropertyType.FLOAT
                        ):
                            if (
                                hasattr(prop_item, "min")
                                and hasattr(prop_item, "max")
                                and range_signal_emitter
                            ):
                                range_signal_emitter.emit(prop_item.min, prop_item.max)
                        elif prop_item.type == ic4.PropertyType.ENUMERATION:
                            if (
                                hasattr(prop_item, "available_enumeration_names")
                                and range_signal_emitter
                            ):
                                range_signal_emitter.emit(
                                    list(prop_item.available_enumeration_names)
                                )

                    if current_val_direct_emitter:
                        if feature_name_camel_case == "ExposureAuto" and isinstance(
                            current_value, str
                        ):
                            current_val_direct_emitter.emit(
                                current_value.lower() != "off"
                            )
                    if properties_update_dict_emitter and current_value is not None:
                        properties_update_dict_emitter.emit(
                            {to_prop_name(feature_name_camel_case): current_value}
                        )

                except ic4.IC4Exception as e:
                    log.warning(
                        f"IC4Exception querying details for '{feature_name_camel_case}': {e} (Code: {e.code})"
                    )
                except AttributeError as e_attr:
                    log.warning(
                        f"AttributeError querying details for '{feature_name_camel_case}': {e_attr}"
                    )
                except Exception as e_gen:
                    log.warning(
                        f"Generic exception querying details for '{feature_name_camel_case}': {e_gen}"
                    )
                return current_value

            initial_props_to_read_camel_case = [
                "AcquisitionFrameRate",
                "ExposureTime",
                "Gain",
                "ExposureAuto",
                "PixelFormat",
                "Width",
                "Height",
            ]
            for prop_name_cc in initial_props_to_read_camel_case:
                range_emitter = None
                direct_emitter = None
                if prop_name_cc == "AcquisitionFrameRate":
                    range_emitter = self.fps_range_updated
                elif prop_name_cc == "ExposureTime":
                    range_emitter = self.exposure_range_updated
                elif prop_name_cc == "Gain":
                    range_emitter = self.gain_range_updated
                elif prop_name_cc == "PixelFormat":
                    range_emitter = self.pixel_formats_updated
                elif prop_name_cc == "ExposureAuto":
                    direct_emitter = self.auto_exposure_updated
                query_property_details(
                    prop_name_cc, range_emitter, direct_emitter, self.properties_updated
                )

            try:
                prop_id_fps_obj = self._propid_map.get("ACQUISITION_FRAME_RATE")
                if prop_id_fps_obj:
                    prop_fps_item = self.pm.find(prop_id_fps_obj.name)
                    if prop_fps_item and prop_fps_item.is_writable:
                        self.pm.set_value(prop_id_fps_obj, self.target_fps)
                        log.info(
                            f"SDKCameraThread: Set initial FPS to {self.target_fps}"
                        )
                        self.properties_updated.emit(
                            {"ACQUISITION_FRAME_RATE": self.target_fps}
                        )
            except Exception as e_fps_set:
                log.warning(
                    f"SDKCameraThread: Could not set initial FPS to {self.target_fps}: {e_fps_set}"
                )

            try:
                self.sink = ic4.QueueSink(listener=self.sink_listener)
                log.info("SDKCameraThread: QueueSink initialized with listener.")
            except Exception as e_sink:
                log.exception(f"Failed to initialize QueueSink: {e_sink}")
                self.camera_error.emit(
                    f"QueueSink init error: {e_sink}", "SINK_INIT_ERROR"
                )
                raise

            log.debug("SDKCameraThread: Setting up stream...")
            self.grabber.stream_setup(
                self.sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            log.info("SDKCameraThread: Stream setup complete, acquisition active.")

            while not self._stop_requested:
                try:
                    # CORRECTED: Call pop_output_buffer without timeout argument
                    buf = self.sink.pop_output_buffer()
                    if not buf:
                        # If pop_output_buffer can return None on non-error (e.g. clean stop), handle it.
                        # Otherwise, a None here might indicate an issue or that the stream stopped.
                        log.debug(
                            "pop_output_buffer returned None, checking stop_requested flag."
                        )
                        if self._stop_requested:
                            break  # Exit loop if stop was requested
                        QThread.msleep(10)  # Brief pause if no buffer and not stopping
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
                    if (
                        e.code == ic4.ErrorCode.Timeout
                    ):  # This might not happen if pop_output_buffer is blocking
                        log.debug("pop_output_buffer timed out (IC4Exception).")
                        continue
                    # For other IC4 errors, log and break
                    log.error(
                        f"IC4Exception in SDKCameraThread acquisition loop: {e} (Code: {e.code})"
                    )
                    self.camera_error.emit(str(e), str(e.code))
                    break
                except Exception as e_loop:
                    log.exception(
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
            if hasattr(self, "sink") and self.sink:
                # Unregister listener if necessary, or rely on __del__
                # self.sink.listener_unregister(self.sink_listener_token) # If token was stored
                pass
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
