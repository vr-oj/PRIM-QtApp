# PRIM-QTAPP/prim_app/threads/sdk_camera_thread.py
import re
import numpy as np
import logging
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal
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
        pass

    def sink_property_changed(
        self, sink: ic4.QueueSink, property_name: str, userdata: any
    ):
        pass


class SDKCameraThread(QThread):
    frame_ready = pyqtSignal(QImage, object)
    camera_error = pyqtSignal(str, str)

    # --- NEW SIGNALS for Phase 2 ---
    camera_info_updated = pyqtSignal(dict)
    # Dict keys: "model", "serial", "width", "height", "pixel_format", "fps"

    exposure_params_updated = pyqtSignal(dict)
    # Dict keys: "auto_options", "auto_current", "auto_is_writable",
    #            "time_current_us", "time_min_us", "time_max_us", "time_is_writable"

    # gain_params_updated = pyqtSignal(dict) # For later

    def __init__(self, device_name=None, fps=10, parent=None):  # fps is target/initial
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
            f"SDKCameraThread initialized for '{self.device_identifier}', target_fps (info): {self.target_fps}"
        )

    def _attempt_set_property(
        self, prop_name: str, value_to_set: any, readable_value_for_log: str = None
    ):
        if readable_value_for_log is None:
            readable_value_for_log = str(value_to_set)
        if not self.pm:
            log.error(f"PM not avail for {prop_name}.")
            return False  # Return success/fail
        prop_item = None
        success = False
        try:
            prop_item = self.pm.find(prop_name)
            if prop_item:
                log.info(
                    f"Attempting to set {prop_name} to {readable_value_for_log}..."
                )
                self.pm.set_value(prop_name, value_to_set)
                rb_val = "(rb N/A)"
                try:
                    rb_val = self.pm.get_value_str(prop_name)
                except Exception as e_rb:
                    log.warning(f"Set {prop_name}, err reading back: {e_rb}")
                log.info(f"Successfully set {prop_name}. Read back: {rb_val}")
                success = True
            else:
                log.warning(f"{prop_name} not found.")
        except ic4.IC4Exception as e_p:
            log.error(
                f"IC4Exc setting {prop_name} to {readable_value_for_log}: {e_p} (Code: {e_p.code})"
            )
        except AttributeError as ae:
            log.error(f"AttrErr for {prop_name} (item type: {type(prop_item)}): {ae}")
        except Exception as e_g:
            log.error(
                f"Generic exc setting {prop_name} to {readable_value_for_log}: {e_g}"
            )
        return success

    def _query_and_emit_camera_parameters(self):
        """Queries key camera parameters and emits them via signals."""
        if not self.pm:
            log.warning("Cannot query camera parameters: PropertyMap not available.")
            return

        try:
            # --- General Camera Info ---
            model = "N/A"
            serial = "N/A"
            width = 0
            height = 0
            pix_fmt_str = "N/A"
            fps_val = 0.0

            prop_model = self.pm.find("DeviceModelName")
            if prop_model and prop_model.is_readable:
                model = prop_model.value_to_str()

            prop_serial = self.pm.find("DeviceSerialNumber")
            if prop_serial and prop_serial.is_readable:
                serial = prop_serial.value_to_str()

            prop_width = self.pm.find("Width")
            if prop_width and prop_width.is_readable:
                width = prop_width.value

            prop_height = self.pm.find("Height")
            if prop_height and prop_height.is_readable:
                height = prop_height.value

            prop_pix_fmt = self.pm.find("PixelFormat")
            if prop_pix_fmt and prop_pix_fmt.is_readable:
                pix_fmt_str = prop_pix_fmt.value_to_str()

            prop_fps = self.pm.find("AcquisitionFrameRate")
            if prop_fps and prop_fps.is_readable:
                fps_val = prop_fps.value
            else:
                fps_val = self.target_fps  # Fallback to target if not readable

            self.camera_info_updated.emit(
                {
                    "model": model,
                    "serial": serial,
                    "width": width,
                    "height": height,
                    "pixel_format": pix_fmt_str,
                    "fps": fps_val,
                }
            )
            log.info(
                f"Emitted camera_info_updated: {model}, {serial}, {width}x{height}, {pix_fmt_str}, FPS:{fps_val:.1f}"
            )

            # --- Exposure Parameters ---
            exp_auto_opts = []
            exp_auto_curr = "Off"
            exp_auto_write = False
            exp_time_curr = 50000.0
            exp_time_min = 10.0
            exp_time_max = 1000000.0
            exp_time_write = False

            prop_exp_auto = self.pm.find("ExposureAuto")
            if prop_exp_auto:
                exp_auto_write = prop_exp_auto.is_writable
                if prop_exp_auto.is_readable:
                    exp_auto_curr = prop_exp_auto.value_to_str()
                if hasattr(
                    prop_exp_auto, "available_entries"
                ):  # Or available_enumeration_names
                    exp_auto_opts = [
                        entry.name for entry in prop_exp_auto.available_entries
                    ]

            prop_exp_time = self.pm.find("ExposureTime")
            if prop_exp_time:
                exp_time_write = prop_exp_time.is_writable
                if prop_exp_time.is_readable:
                    exp_time_curr = prop_exp_time.value
                if hasattr(prop_exp_time, "min"):
                    exp_time_min = prop_exp_time.min
                if hasattr(prop_exp_time, "max"):
                    exp_time_max = prop_exp_time.max

            self.exposure_params_updated.emit(
                {
                    "auto_options": exp_auto_opts,
                    "auto_current": exp_auto_curr,
                    "auto_is_writable": exp_auto_write,
                    "time_current_us": exp_time_curr,
                    "time_min_us": exp_time_min,
                    "time_max_us": exp_time_max,
                    "time_is_writable": exp_time_write,
                }
            )
            log.info(
                f"Emitted exposure_params_updated: Auto={exp_auto_curr} (Opts:{exp_auto_opts}), Time={exp_time_curr}us (Min:{exp_time_min}, Max:{exp_time_max})"
            )

            # TODO: Query and emit Gain parameters similarly

        except Exception as e_query:
            log.error(f"Error querying and emitting camera parameters: {e_query}")

    def run(self):
        try:
            # ... (device discovery and open logic - keep as is from your last working version) ...
            all_devices = ic4.DeviceEnum.devices()
            if not all_devices:
                raise RuntimeError("No IC4 devices found")
            target_dev = None
            if self.device_identifier:
                for dev in all_devices:
                    ds, du, dm = (
                        (dev.serial if hasattr(dev, "serial") else ""),
                        (dev.unique_name if hasattr(dev, "unique_name") else ""),
                        (dev.model_name if hasattr(dev, "model_name") else ""),
                    )
                    if self.device_identifier in [ds, du, dm]:
                        target_dev = dev
                        log.info(f"Found: {dm} SN:{ds} U:{du}")
                        break
                if not target_dev:
                    raise RuntimeError(f"Cam '{self.device_identifier}' not found.")
            else:
                target_dev = devices[0]
                log.info(f"Using first dev: {target_dev.model_name}")

            log.info(f"SDKCameraThread opening: {target_dev.model_name}")
            self.grabber = ic4.Grabber()
            self.grabber.device_open(target_dev)
            self.pm = self.grabber.device_property_map
            log.info(f"Device {target_dev.model_name} opened. PM acquired.")

            log.info("Attempting to configure camera properties...")
            self._attempt_set_property("PixelFormat", ic4.PixelFormat.Mono8, "Mono8")
            self._attempt_set_property("Width", 640, "640")
            self._attempt_set_property("Height", 480, "480")
            self._attempt_set_property("AcquisitionMode", "Continuous", "Continuous")
            self._attempt_set_property("TriggerMode", "Off", "Off")
            # Set ExposureAuto to Off initially to enable manual ExposureTime control test
            self._attempt_set_property("ExposureAuto", "Off", "Off")
            log.info("Finished attempt to configure camera properties.")

            # --- Query and emit initial parameters for UI ---
            self._query_and_emit_camera_parameters()  # NEW CALL

            self.sink = ic4.QueueSink(listener=self.sink_listener)
            log.info("QueueSink initialized.")
            log.debug("Calling stream_setup...")
            self.grabber.stream_setup(self.sink)
            log.info("stream_setup completed.")

            if not self.grabber.is_acquisition_active:
                log.warning(
                    "Acquisition NOT active post stream_setup. Attempting explicit start..."
                )
                self.grabber.acquisition_start()
                if not self.grabber.is_acquisition_active:
                    log.error("Explicit acquisition_start FAILED.")
                    raise RuntimeError("Camera acquisition failed to start.")
                else:
                    log.info("Explicit acquisition_start SUCCEEDED.")
            else:
                log.info("Acquisition IS active post stream_setup.")

            log.info("Stream active. Pausing briefly...")
            QThread.msleep(250)
            log.info("Pause complete. Entering frame loop...")

            while not self._stop_requested:
                # ... (your existing frame acquisition loop logic - which was working) ...
                buf = None
                try:
                    buf = self.sink.pop_output_buffer()
                    if buf:
                        arr = buf.numpy_wrap()
                        q_image_format = QImage.Format_Grayscale8
                        if arr.ndim == 3 and arr.shape[2] == 3:
                            q_image_format = QImage.Format_BGR888
                        elif arr.ndim == 2 or (arr.ndim == 3 and arr.shape[2] == 1):
                            q_image_format = QImage.Format_Grayscale8
                        else:
                            log.warning(f"Unsupported arr shape: {arr.shape}. Skip.")
                            if buf:
                                buf.release()
                            continue
                        final_arr = (
                            arr[..., 0]
                            if (
                                arr.ndim == 3
                                and q_image_format == QImage.Format_Grayscale8
                                and arr.shape[2] == 1
                            )
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
                    else:
                        if self._stop_requested:
                            log.debug("Stop requested, buffer None, exit loop.")
                            break
                        QThread.msleep(10)
                        continue
                except ic4.IC4Exception as e:
                    if e.code in [ic4.ErrorCode.Timeout, ic4.ErrorCode.NoData]:
                        if self._stop_requested:
                            break
                        QThread.msleep(5 if e.code == ic4.ErrorCode.NoData else 1)
                        continue
                    else:
                        log.error(
                            f"Unhandled IC4Exception in loop: {e} (Code:{e.code}), breaking."
                        )
                        self.camera_error.emit(str(e), str(e.code))
                        break
                except AttributeError as ae:
                    log.error(f"AttributeError in loop: {ae}")
                    self.camera_error.emit(str(ae), "ATTR_ERR_BUF")
                    if buf and hasattr(buf, "release"):
                        try:
                            buf.release()
                        except Exception as e_rls:
                            log.error(f"Err releasing buf after AttrErr: {e_rls}")
                    break
                except Exception as e_loop:
                    log.exception(f"Generic exception in loop: {e_loop}")
                    self.camera_error.emit(str(e_loop), "LOOP_ERR")
                    if buf and hasattr(buf, "release"):
                        try:
                            buf.release()
                        except Exception as e_rls:
                            log.error(f"Err releasing buf after GenExc: {e_rls}")
                    break
            log.info("SDKCameraThread: Exited acquisition loop.")
        # ... (rest of your existing exception handlers and finally block) ...
        except RuntimeError as e_rt:
            log.error(f"RuntimeError in SDKCameraThread.run: {e_rt}")
            self.camera_error.emit(str(e_rt), "RUNTIME_SETUP_ERROR")
        except ic4.IC4Exception as e_ic4_setup:
            log.error(
                f"IC4Exception during setup phase: {e_ic4_setup} (Code:{e_ic4_setup.code})"
            )
            self.camera_error.emit(str(e_ic4_setup), str(e_ic4_setup.code))
        except Exception as ex_outer:
            log.exception(f"Outer unhandled exception in run: {ex_outer}")
            self.camera_error.emit(str(ex_outer), type(ex_outer).__name__)
        finally:
            log.debug("SDKCameraThread.run() finally block.")
            if self.grabber:
                try:
                    if self.grabber.is_acquisition_active:
                        log.debug("Stopping acquisition (finally)...")
                        self.grabber.acquisition_stop()
                except Exception as e:
                    log.error(f"Finally: Error stopping acquisition: {e}")
                try:
                    if self.grabber.is_device_open:
                        log.debug("Closing device (finally)...")
                        self.grabber.device_close()
                except Exception as e:
                    log.error(f"Finally: Error closing device: {e}")
            self.grabber = None
            self.pm = None
            log.info("SDKCameraThread: run method finished cleanup.")

    def stop(self):  # Your existing stop method is likely fine
        log.info(f"SDKCameraThread.stop() for {self.device_identifier}.")
        self._stop_requested = True
        if self.isRunning():
            log.debug(f"Waiting for {self.device_identifier} to finish...")
            if not self.wait(3000):
                log.warning(f"{self.device_identifier} unresponsive, terminating.")
                self.terminate()
                self.wait(500)
            else:
                log.info(f"{self.device_identifier} finished gracefully.")
        else:
            log.info(f"{self.device_identifier} not running when stop called.")
        log.info(f"SDKCameraThread.stop() completed for {self.device_identifier}.")
