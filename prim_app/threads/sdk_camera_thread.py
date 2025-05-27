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
    # Order might matter for some properties that could be ambiguously read (e.g. enum as int or string)
    # Prioritize string for enums if that's how they are set, then bool, then specific number types.
    # However, for general numeric properties, int/float should come before string.
    # This function's current order is a bit of a guess without knowing specific property types.

    # Attempt to get PropertyType for more specific getter (conceptual)
    # try:
    #     prop_info = pm.get_property(pid) # Assuming such a method exists
    #     prop_type = prop_info.type # Assuming type is an enum like ic4.PropertyType.INTEGER
    #     if prop_type == ic4.PropertyType.INTEGER: return pm.get_value_int(pid)
    #     # ... etc.
    # except Exception:
    #     pass # Fallback to trying all

    # Fallback: try common getters
    try:
        return pm.get_value_int(pid)
    except ic4.IC4Exception:
        pass
    try:
        return pm.get_value_float(pid)
    except ic4.IC4Exception:
        pass
    try:
        return pm.get_value_str(pid)  # Often useful for enums
    except ic4.IC4Exception:
        pass
    try:
        return pm.get_value_bool(pid)
    except ic4.IC4Exception:
        pass

    log.debug(f"Could not read value for PID: {pid}")
    return None


class SDKCameraThread(QThread):
    """
    Thread to grab live frames from a DMK camera using IC Imaging Control 4.
    Emits QImage frames, raw numpy arrays, and camera property updates.
    """

    frame_ready = pyqtSignal(QImage, object)
    resolutions_updated = pyqtSignal(list)
    pixel_formats_updated = pyqtSignal(list)
    fps_range_updated = pyqtSignal(float, float)
    exposure_range_updated = pyqtSignal(float, float)
    gain_range_updated = pyqtSignal(float, float)
    auto_exposure_updated = pyqtSignal(bool)
    properties_updated = pyqtSignal(dict)
    camera_error = pyqtSignal(str, str)

    # --- CORRECTED _propid_map INITIALIZATION ---
    _propid_map = {
        name: getattr(ic4.PropId, name)
        for name in dir(ic4.PropId)
        if not name.startswith("_") and not callable(getattr(ic4.PropId, name))
    }
    # --- END CORRECTION ---

    def __init__(self, device_name=None, fps=10, parent=None):
        super().__init__(parent)
        self.device_name = device_name  # Should be serial number
        self.fps = fps
        self._stop_requested = False
        self.grabber = None
        self.pm = None  # device property map

    def apply_node_settings(self, settings: dict):
        if not self.grabber or not self.pm:
            log.warning("Apply_node_settings called but grabber or pm not initialized.")
            return

        applied = {}

        for key, val in settings.items():
            pid_name = to_prop_name(key)  # e.g., "EXPOSURE_TIME" from "ExposureTime"
            pid = self._propid_map.get(pid_name)

            if not pid:
                log.error(
                    f"Unknown property name: '{key}' (converted to '{pid_name}') in _propid_map."
                )
                self.camera_error.emit(f"Unknown property '{key}'", "")
                continue

            try:
                log.debug(
                    f"Attempting to set {pid_name} (PID: {pid}) to {val} (type: {type(val)})"
                )

                # Special handling for PixelFormat if it expects an enum member
                if pid_name == "PIXEL_FORMAT" and isinstance(val, str):
                    try:
                        # Attempt to get the PixelFormat enum member from ic4.PixelFormat
                        pixel_format_member = getattr(ic4.PixelFormat, val, None)
                        if pixel_format_member is not None:
                            log.debug(
                                f"Converted PixelFormat string '{val}' to enum member {pixel_format_member}"
                            )
                            self.pm.set_value(pid, pixel_format_member)
                        else:
                            # Fallback to trying string if direct enum member not found by that name
                            log.warning(
                                f"PixelFormat enum member for '{val}' not found, trying string directly."
                            )
                            self.pm.set_value(pid, val)
                    except Exception as e_pf:
                        log.error(f"Error setting PixelFormat '{val}': {e_pf}")
                        self.camera_error.emit(
                            f"Failed to set {pid_name} to {val}: {e_pf}",
                            getattr(e_pf, "code", ""),
                        )
                        continue
                elif pid_name == "EXPOSURE_AUTO" and isinstance(
                    val, str
                ):  # "Off" or "Continuous"
                    self.pm.set_value(pid, val)
                elif isinstance(val, (int, float, bool, str)):  # General case
                    self.pm.set_value(pid, val)
                else:
                    log.warning(f"Unsupported value type for {pid_name}: {type(val)}")
                    self.camera_error.emit(f"Unsupported type for {pid_name}", "")
                    continue

                actual = read_current(self.pm, pid)
                log.info(f"Successfully set {pid_name} to {val}, read back: {actual}")
                applied[pid_name] = actual  # Store with UPPER_SNAKE_CASE name
            except ic4.IC4Exception as e:
                log.error(
                    f"IC4Exception setting {pid_name} to {val}: {e} (Code: {e.code})"
                )
                self.camera_error.emit(
                    f"Failed to set {pid_name} to {val}: {e}",
                    str(e.code),
                )
            except Exception as e_gen:
                log.error(f"Generic Exception setting {pid_name} to {val}: {e_gen}")
                self.camera_error.emit(
                    f"Failed to set {pid_name} to {val}: {e_gen}",
                    "",
                )

        if applied:
            self.properties_updated.emit(applied)

    def run(self):
        try:
            devices = ic4.DeviceEnum.devices()
            if not devices:
                log.error("No camera devices found by ic4.DeviceEnum")
                raise RuntimeError("No camera devices found")

            # Ensure device_name (serial number) is correctly used for matching
            target_device_info = None
            if self.device_name:  # self.device_name should be the serial number
                for dev_info in devices:
                    if dev_info.serial_number == self.device_name:
                        target_device_info = dev_info
                        break
                if not target_device_info:
                    log.error(
                        f"Camera with serial number '{self.device_name}' not found. Available: {[d.serial_number for d in devices]}"
                    )
                    raise RuntimeError(
                        f"Camera with serial '{self.device_name}' not found."
                    )
            else:  # If no device_name, use the first one (if any)
                target_device_info = devices[0]

            log.info(
                f"Attempting to open device: {target_device_info.model_name} (SN: {target_device_info.serial_number})"
            )

            self.grabber = ic4.Grabber()
            self.grabber.device_open(target_device_info)
            self.pm = self.grabber.device_property_map  # Assign to instance variable
            log.info(f"Device {target_device_info.serial_number} opened successfully.")

            # Report available resolutions & pixel formats
            # This part for video_modes might be TIS specific or not standard GenICam.
            # GenICam typically has Width, Height, PixelFormat as separate properties.
            # For now, we'll rely on direct PropId for Width, Height, PixelFormat.
            # self.resolutions_updated.emit([]) # Emit empty or use GenICam Width/Height ranges if available
            # self.pixel_formats_updated.emit([]) # Emit empty or use GenICam PixelFormat enum options

            def get_prop_range(prop_id, prop_name_for_log):
                try:
                    min_val = self.pm.get_min(prop_id)
                    max_val = self.pm.get_max(prop_id)
                    log.debug(f"{prop_name_for_log} range: {min_val} - {max_val}")
                    return min_val, max_val
                except ic4.IC4Exception as e:
                    log.warning(
                        f"{prop_name_for_log} range not available: {e} (Code: {e.code})"
                    )
                    # Emit a sensible default or indicate unavailability
                    if prop_name_for_log == "FPS":
                        self.fps_range_updated.emit(1, 100)  # Example default
                    elif prop_name_for_log == "Exposure":
                        self.exposure_range_updated.emit(10, 1000000)  # Example default
                    elif prop_name_for_log == "Gain":
                        self.gain_range_updated.emit(0, 480)  # Example default
                    return None, None

            fps_min, fps_max = get_prop_range(ic4.PropId.ACQUISITION_FRAME_RATE, "FPS")
            if fps_min is not None:
                self.fps_range_updated.emit(fps_min, fps_max)
            # Try to set initial FPS if possible
            try:
                if self.pm.is_writable(ic4.PropId.ACQUISITION_FRAME_RATE):
                    self.pm.set_value(
                        ic4.PropId.ACQUISITION_FRAME_RATE, float(self.fps)
                    )
                    log.info(f"Set initial FPS to {self.fps}")
            except ic4.IC4Exception as e:
                log.warning(f"Could not set initial FPS to {self.fps}: {e}")

            exp_min, exp_max = get_prop_range(ic4.PropId.EXPOSURE_TIME, "Exposure")
            if exp_min is not None:
                self.exposure_range_updated.emit(exp_min, exp_max)

            try:
                auto_val_str = self.pm.get_value_str(
                    ic4.PropId.EXPOSURE_AUTO
                )  # "Off", "Continuous"
                self.auto_exposure_updated.emit(auto_val_str != "Off")
            except ic4.IC4Exception as e:
                log.warning(f"Could not read ExposureAuto: {e}. Assuming Off/False.")
                self.auto_exposure_updated.emit(False)

            gain_min, gain_max = get_prop_range(ic4.PropId.GAIN, "Gain")
            if gain_min is not None:
                self.gain_range_updated.emit(gain_min, gain_max)

            init_props = {}
            for pid_name_upper in [
                "EXPOSURE_TIME",
                "GAIN",
                "PIXEL_FORMAT",
                "ACQUISITION_FRAME_RATE",
                "WIDTH",
                "HEIGHT",
            ]:
                prop_id_obj = self._propid_map.get(pid_name_upper)
                if prop_id_obj:
                    val = read_current(self.pm, prop_id_obj)
                    if val is not None:
                        init_props[pid_name_upper] = (
                            val  # Use UPPER_SNAKE_CASE consistently for keys from this point
                        )
            if init_props:
                log.info(f"Initial properties read: {init_props}")
                self.properties_updated.emit(init_props)

            sink = ic4.QueueSink()
            log.debug("Setting up stream...")
            self.grabber.stream_setup(
                sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            # acquisition_start is often implicit with StreamSetupOption.ACQUISITION_START
            # but can be called explicitly if needed, or if that option is not used.
            # self.grabber.acquisition_start()
            log.info("Stream setup complete, acquisition should be active.")

            while not self._stop_requested:
                try:
                    buf = sink.pop_output_buffer(1000)  # Timeout in ms
                    if not buf:  # Timeout can result in None
                        # log.debug("pop_output_buffer timed out")
                        continue

                    arr = buf.numpy_wrap()

                    # Determine image format for QImage
                    # This needs to be robust based on actual PixelFormat from camera
                    # For example, if PixelFormat is BayerRG8, it needs debayering for color.
                    # Current code assumes RGB or Mono.

                    pixel_format_str = init_props.get(
                        "PIXEL_FORMAT", ""
                    ).upper()  # Get current pixel format string

                    if (
                        arr.ndim == 3 and arr.shape[2] == 3
                    ):  # Assuming BGR from camera if 3 channels
                        # Create QImage from BGR data
                        q_image = QImage(
                            arr.data,
                            arr.shape[1],
                            arr.shape[0],
                            arr.strides[0],
                            QImage.Format_BGR888,
                        )
                    elif arr.ndim == 2 or (
                        arr.ndim == 3 and arr.shape[2] == 1
                    ):  # Grayscale
                        mono_arr = arr[..., 0] if arr.ndim == 3 else arr
                        q_image = QImage(
                            mono_arr.data,
                            mono_arr.shape[1],
                            mono_arr.shape[0],
                            mono_arr.strides[0],
                            QImage.Format_Grayscale8,
                        )  # Or Format_Indexed8
                    else:
                        log.warning(
                            f"Unsupported numpy array shape for QImage: {arr.shape}, format: {pixel_format_str}"
                        )
                        buf.release()
                        continue

                    self.frame_ready.emit(q_image.copy(), arr.copy())  # Emit copies
                    buf.release()

                except ic4.IC4Exception as e:
                    if e.code == ic4.ErrorCode.Timeout:
                        # log.debug("pop_output_buffer timed out (IC4Exception)")
                        continue
                    log.error(f"IC4Exception in acquisition loop: {e} (Code: {e.code})")
                    self.camera_error.emit(str(e), str(e.code))
                    break  # Exit loop on other IC4 errors
                except Exception as e_loop:
                    log.error(f"Generic exception in acquisition loop: {e_loop}")
                    self.camera_error.emit(str(e_loop), "")
                    break

            log.info("Exited acquisition loop.")

        except (
            RuntimeError
        ) as e_rt:  # Catch specific RuntimeError for "No camera devices found" etc.
            log.error(f"RuntimeError in SDKCameraThread.run: {e_rt}")
            self.camera_error.emit(str(e_rt), "RUNTIME_ERROR")
        except ic4.IC4Exception as e_ic4_setup:
            log.error(
                f"IC4Exception during setup in SDKCameraThread.run: {e_ic4_setup} (Code: {e_ic4_setup.code})"
            )
            self.camera_error.emit(str(e_ic4_setup), str(e_ic4_setup.code))
        except Exception as ex_outer:
            log.error(f"Outer exception in SDKCameraThread.run: {ex_outer}")
            code = getattr(ex_outer, "code", "")
            self.camera_error.emit(str(ex_outer), str(code))
        finally:
            log.debug("SDKCameraThread.run() entering finally block for cleanup.")
            if self.grabber:
                try:
                    if self.grabber.is_acquisition_active():  # Check before stopping
                        log.debug("Stopping acquisition...")
                        self.grabber.acquisition_stop()
                except Exception as e_acq_stop:
                    log.error(f"Exception during acquisition_stop: {e_acq_stop}")

                # stream_stop might not be necessary if acquisition_stop handles it,
                # but explicit can be safer.
                # try:
                #    log.debug("Stopping stream...")
                #    self.grabber.stream_stop() # Often implicit with acquisition_stop
                # except Exception as e_stream_stop:
                #    log.error(f"Exception during stream_stop: {e_stream_stop}")

                try:
                    if self.grabber.is_device_open():  # Check before closing
                        log.debug("Closing device...")
                        self.grabber.device_close()
                except Exception as e_dev_close:
                    log.error(f"Exception during device_close: {e_dev_close}")
            self.grabber = None
            self.pm = None
            log.info("SDKCameraThread finished.")

    def stop(self):
        """Signal the thread to stop and wait for exit."""
        log.info("SDKCameraThread.stop() called.")
        self._stop_requested = True
        if self.isRunning():  # Only wait if the thread is actually running
            if not self.wait(3000):  # Wait for 3 seconds
                log.warning("SDKCameraThread did not exit gracefully, terminating.")
                self.terminate()  # Forcefully terminate if not stopped
                self.wait(500)  # Wait a bit after terminate
        log.info("SDKCameraThread.stop() completed.")
