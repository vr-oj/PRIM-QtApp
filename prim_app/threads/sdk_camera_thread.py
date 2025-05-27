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

    def sink_disconnected(self, sink: ic4.QueueSink, userdata: any):
        log.debug(f"Listener '{self.owner_name}': Sink disconnected.")
        pass

    def sink_property_changed(
        self, sink: ic4.QueueSink, property_name: str, userdata: any
    ):
        pass


def read_current(pm: ic4.PropertyMap, feature_name_sfnc: str):
    """
    Try each typed getter until one succeeds, return the first value or None.
    `feature_name_sfnc` is the GenICam SFNC string name (e.g., "ExposureTime").
    """
    if feature_name_sfnc in ["PixelFormat", "ExposureAuto", "TriggerMode"]:
        try:
            return pm.get_value_str(feature_name_sfnc)
        except ic4.IC4Exception:
            pass

    try:
        return pm.get_value_float(feature_name_sfnc)
    except ic4.IC4Exception:
        pass
    try:
        return pm.get_value_int(feature_name_sfnc)
    except ic4.IC4Exception:
        pass
    try:
        return pm.get_value_bool(feature_name_sfnc)
    except ic4.IC4Exception:
        pass

    if feature_name_sfnc not in ["PixelFormat", "ExposureAuto", "TriggerMode"]:
        try:
            return pm.get_value_str(feature_name_sfnc)
        except ic4.IC4Exception:
            pass

    log.debug(
        f"Could not read current value for property via standard getters: {feature_name_sfnc}"
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
        for feature_name_sfnc, val in settings.items():
            try:
                log.debug(
                    f"Attempting to set GenICam Feature '{feature_name_sfnc}' to {val} (type: {type(val)})"
                )

                if feature_name_sfnc == "PixelFormat" and isinstance(val, str):
                    pixel_format_member = getattr(ic4.PixelFormat, val, None)
                    if pixel_format_member is not None:
                        self.pm.set_value(feature_name_sfnc, pixel_format_member)
                    else:
                        self.pm.set_value(feature_name_sfnc, val)
                elif feature_name_sfnc == "ExposureAuto" and isinstance(val, str):
                    self.pm.set_value(feature_name_sfnc, val)
                else:
                    self.pm.set_value(feature_name_sfnc, val)

                current_val_after_set = read_current(self.pm, feature_name_sfnc)
                log.info(
                    f"Successfully set feature '{feature_name_sfnc}' to {val}, read back: {current_val_after_set}"
                )
                applied[to_prop_name(feature_name_sfnc)] = current_val_after_set
            except ic4.IC4Exception as e:
                log.error(
                    f"IC4Exception setting feature '{feature_name_sfnc}' to {val}: {e} (Code: {e.code})"
                )
                self.camera_error.emit(
                    f"Failed to set '{feature_name_sfnc}' to {val}: {e}", str(e.code)
                )
            except Exception as e_gen:
                log.exception(
                    f"Generic Exception setting feature '{feature_name_sfnc}' to {val}: {e_gen}"
                )
                self.camera_error.emit(
                    f"Failed to set '{feature_name_sfnc}' to {val}: {e_gen}", ""
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
                feature_name_sfnc,
                range_signal_emitter=None,
                current_val_direct_emitter=None,
                properties_update_dict_emitter=None,
            ):
                current_value = None
                try:
                    prop_item = self.pm.find(feature_name_sfnc)
                    if prop_item is None:
                        log.warning(
                            f"GenICam Feature '{feature_name_sfnc}' not found in PropertyMap via find(). Trying direct read."
                        )
                        current_value = read_current(self.pm, feature_name_sfnc)
                        if current_value is None:
                            log.warning(
                                f"Still could not read current value for {feature_name_sfnc} directly."
                            )
                            return None
                        log.debug(
                            f"Read current value for {feature_name_sfnc} directly (find failed): {current_value}"
                        )
                    else:
                        current_value = prop_item.value
                        log.debug(
                            f"Property '{feature_name_sfnc}': Type={prop_item.type}, Value={current_value}"
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
                        if feature_name_sfnc == "ExposureAuto" and isinstance(
                            current_value, str
                        ):
                            current_val_direct_emitter.emit(
                                current_value.lower() != "off"
                            )
                    if properties_update_dict_emitter and current_value is not None:
                        properties_update_dict_emitter.emit(
                            {to_prop_name(feature_name_sfnc): current_value}
                        )

                except ic4.IC4Exception as e:
                    log.warning(
                        f"IC4Exception querying details for '{feature_name_sfnc}': {e} (Code: {e.code})"
                    )
                except AttributeError as e_attr:
                    log.warning(
                        f"AttributeError querying details for '{feature_name_sfnc}': {e_attr}"
                    )
                except Exception as e_gen:
                    log.warning(
                        f"Generic exception querying details for '{feature_name_sfnc}': {e_gen}"
                    )
                return current_value

            # Use HARDCODED SFNC strings for querying
            initial_props_to_read_sfnc = [
                "AcquisitionFrameRate",
                "ExposureTime",
                "Gain",
                "ExposureAuto",
                "PixelFormat",
                "Width",
                "Height",
            ]
            for prop_sfnc_name in initial_props_to_read_sfnc:
                range_emitter = None
                direct_emitter = None
                if prop_sfnc_name == "AcquisitionFrameRate":
                    range_emitter = self.fps_range_updated
                elif prop_sfnc_name == "ExposureTime":
                    range_emitter = self.exposure_range_updated
                elif prop_sfnc_name == "Gain":
                    range_emitter = self.gain_range_updated
                elif prop_sfnc_name == "PixelFormat":
                    range_emitter = self.pixel_formats_updated
                elif prop_sfnc_name == "ExposureAuto":
                    direct_emitter = self.auto_exposure_updated
                query_property_details(
                    prop_sfnc_name,
                    range_emitter,
                    direct_emitter,
                    self.properties_updated,
                )

            try:
                fps_sfnc_name = "AcquisitionFrameRate"  # Use hardcoded SFNC string
                prop_fps_item = self.pm.find(fps_sfnc_name)
                if prop_fps_item and prop_fps_item.is_writable:
                    self.pm.set_value(fps_sfnc_name, self.target_fps)
                    log.info(f"SDKCameraThread: Set initial FPS to {self.target_fps}")
                    self.properties_updated.emit(
                        {to_prop_name(fps_sfnc_name): self.target_fps}
                    )
                elif not prop_fps_item:
                    log.warning(
                        f"SDKCameraThread: Could not find property '{fps_sfnc_name}' to set initial FPS."
                    )
                else:
                    log.warning(
                        f"SDKCameraThread: Property '{fps_sfnc_name}' is not writable. Cannot set initial FPS."
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
            if not self.grabber.is_acquisition_active:
                log.info("SDKCameraThread: Explicitly starting acquisition...")
                self.grabber.acquisition_start()
            log.info("SDKCameraThread: Stream setup and acquisition active.")

            while not self._stop_requested:
                try:
                    buf = self.sink.pop_output_buffer()
                    if not buf:
                        if self._stop_requested:
                            break
                        QThread.msleep(10)
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
                        log.debug("pop_output_buffer timed out (IC4Exception).")
                        continue
                    elif e.code == ic4.ErrorCode.NoData:
                        log.debug("pop_output_buffer returned NoData. Continuing.")
                        QThread.msleep(5)
                        continue
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
