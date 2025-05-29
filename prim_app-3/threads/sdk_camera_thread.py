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
            f"SDKCameraThread (Simplified) initialized for device_identifier: '{self.device_identifier}', target_fps (informational): {self.target_fps}"
        )

    def _attempt_set_property(
        self, prop_name: str, value_to_set: any, readable_value_for_log: str = None
    ):
        """
        Attempts to set a camera property. Relies on exceptions for non-writable or invalid values.
        """
        if readable_value_for_log is None:
            readable_value_for_log = str(value_to_set)

        if not self.pm:
            log.error(f"PropertyMap not available. Cannot set {prop_name}.")
            return

        prop_item = None  # Define for use in exception logging if find itself fails
        try:
            prop_item = self.pm.find(prop_name)
            if prop_item:
                log.info(
                    f"Attempting to set {prop_name} to {readable_value_for_log}..."
                )
                self.pm.set_value(prop_name, value_to_set)

                read_back_value_str = "(readback N/A)"
                try:
                    read_back_value_str = self.pm.get_value_str(prop_name)
                except Exception as e_rb:
                    log.warning(
                        f"Set {prop_name}, but failed to read back string value: {e_rb}"
                    )
                log.info(
                    f"Successfully set {prop_name}. Read back: {read_back_value_str}"
                )
            else:
                log.warning(f"{prop_name} property not found on camera.")
        except ic4.IC4Exception as e_prop:
            log.error(
                f"IC4Exception while setting {prop_name} to {readable_value_for_log}: {e_prop} (Code: {e_prop.code})"
            )
        except AttributeError as ae:
            log.error(
                f"AttributeError operating on {prop_name} (prop_item type: {type(prop_item)}): {ae}"
            )
        except Exception as e_gen:
            log.error(
                f"Generic exception while setting {prop_name} to {readable_value_for_log}: {e_gen}"
            )

    def set_camera_property(self, name, value):
        if not hasattr(self, "device") or self.device is None:
            log.warning(f"[SDKCameraThread] No active device to apply {name}")
            return
        if not hasattr(self, "grabber") or self.grabber is None:
            log.warning("[SDKCameraThread] Grabber not initialized.")
            return

        try:
            if name == "Resolution":
                # Handle resolution in format "Width×Height"
                w, h = map(int, value.split("×"))
                self.device.set_property("Width", w)
                self.device.set_property("Height", h)
                log.info(f"[SDKCameraThread] Set resolution to {w}x{h}")
            elif name == "FPS":
                self.device.set_property("AcquisitionFrameRate", float(value))
                log.info(f"[SDKCameraThread] Set FPS to {value}")
            else:
                self.device.set_property(name, value)
                log.info(f"[SDKCameraThread] Set {name} to {value}")
        except Exception as e:
            log.warning(f"[SDKCameraThread] Failed to set {name}: {e}")

    def run(self):
        try:
            all_devices = ic4.DeviceEnum.devices()
            if not all_devices:
                raise RuntimeError("No camera devices found by IC4 DeviceEnum")

            target_device_info = None
            if self.device_identifier:
                for dev_info in all_devices:
                    current_serial = (
                        dev_info.serial
                        if hasattr(dev_info, "serial") and dev_info.serial
                        else ""
                    )
                    current_unique_name = (
                        dev_info.unique_name
                        if hasattr(dev_info, "unique_name") and dev_info.unique_name
                        else ""
                    )
                    current_model_name = (
                        dev_info.model_name if hasattr(dev_info, "model_name") else ""
                    )
                    if (
                        self.device_identifier == current_serial
                        or self.device_identifier == current_unique_name
                        or self.device_identifier == current_model_name
                    ):
                        target_device_info = dev_info
                        log.info(
                            f"Found device: {current_model_name}, SN:{current_serial}, Unique:{current_unique_name}"
                        )
                        break
                if not target_device_info:
                    raise RuntimeError(f"Camera '{self.device_identifier}' not found.")
            elif all_devices:
                target_device_info = all_devices[0]
                log.info(f"Using first device: {target_device_info.model_name}")
            else:
                raise RuntimeError("No devices available.")

            log.info(f"SDKCameraThread opening: {target_device_info.model_name}")
            self.grabber = ic4.Grabber()
            self.grabber.device_open(target_device_info)
            self.device = self.grabber.device_opened()  # This returns the Device object
            self.pm = self.grabber.device_property_map
            log.info(f"Device {target_device_info.model_name} opened. PM acquired.")

            log.info("Attempting to configure camera properties...")
            self._attempt_set_property("PixelFormat", ic4.PixelFormat.Mono8, "Mono8")
            self._attempt_set_property("Width", 640, "640")
            self._attempt_set_property("Height", 480, "480")
            self._attempt_set_property("AcquisitionMode", "Continuous", "Continuous")
            self._attempt_set_property("TriggerMode", "Off", "Off")
            log.info("Finished attempt to configure camera properties.")

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
                buf = None
                try:
                    buf = self.sink.pop_output_buffer()
                    if buf:
                        # log.debug(f"Popped buffer: {type(buf)}") # Reduce log spam
                        arr = buf.numpy_wrap()
                        q_image_format = QImage.Format_Grayscale8
                        if arr.ndim == 3 and arr.shape[2] == 3:
                            q_image_format = QImage.Format_BGR888
                        elif arr.ndim == 2 or (arr.ndim == 3 and arr.shape[2] == 1):
                            q_image_format = QImage.Format_Grayscale8
                        else:
                            log.warning(f"Unsupported arr shape: {arr.shape}. Skip.")
                            if buf:
                                buf.release()  # Ensure release if skipping
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
                        # pop_output_buffer returned None or falsy
                        # log.debug("pop_output_buffer returned None/falsy. Checking stop.") # Reduce log spam
                        if self._stop_requested:
                            log.debug("Stop requested, buffer None, exit loop.")
                            break
                        QThread.msleep(10)
                        continue  # Brief pause if no data
                except ic4.IC4Exception as e:
                    # log.warning(f"IC4Exception in loop: {e} (Code: {e.code})") # Reduce log spam
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

        except RuntimeError as e_rt:
            log.error(f"RuntimeError in SDKCameraThread.run: {e_rt}")
            self.camera_error.emit(str(e_rt), "RUNTIME_SETUP_ERROR")
        except ic4.IC4Exception as e_ic4_setup:
            log.error(
                f"IC4Exception during setup phase: {e_ic4_setup} (Code:{e_ic4_setup.code})"
            )  # Corrected line number in log analysis
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

    def stop(self):
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
