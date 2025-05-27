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
        pass  # Frame processing is handled by popping buffer in the thread's loop

    def frames_queued(self, sink: ic4.QueueSink):  # Corrected: Removed userdata
        # log.debug(f"Listener '{self.owner_name}': Frames queued for {sink}.")
        pass

    def sink_connected(
        self, sink: ic4.QueueSink, image_type_proposed: ic4.ImageType, userdata: any
    ) -> bool:
        log.debug(
            f"Listener '{self.owner_name}': Sink connected. Grabber proposed ImageType: {image_type_proposed}. Accepting."
        )
        return True

    def sink_disconnected(self, sink: ic4.QueueSink):  # Corrected: Removed userdata
        log.debug(f"Listener '{self.owner_name}': Sink disconnected from {sink}.")
        pass

    def sink_property_changed(
        self,
        sink: ic4.QueueSink,
        property_name: str,
        userdata: any,  # Assuming userdata is passed by SDK here
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

    def _try_set_property(self, prop_name: str, value: any, value_type: str):
        """Helper to set a property and log outcome."""
        try:
            prop_item = self.pm.find(prop_name)
            if prop_item:
                if prop_item.is_writable:
                    actual_value_to_set = value
                    if value_type == "enum" and isinstance(
                        value, str
                    ):  # For string representation of enum
                        # Find the enum member by string value
                        enum_member = getattr(
                            ic4.PixelFormat, value, None
                        )  # Example for PixelFormat
                        if prop_name == "ExposureAuto":  # Example for ExposureAuto
                            enum_member = getattr(ic4.ExposureAuto, value, None)
                        # Add more enum types as needed
                        if enum_member is not None:
                            actual_value_to_set = enum_member
                        else:  # Try to set string directly if specific enum member not found (some SDKs allow)
                            log.warning(
                                f"Enum member for '{value}' not found in known ic4 enums for {prop_name}. Trying to set string directly."
                            )

                    self.pm.set_value(prop_name, actual_value_to_set)

                    # Read back and log
                    read_back_value_str = "N/A"
                    if value_type == "int":
                        read_back_value_str = str(self.pm.get_value_int(prop_name))
                    elif value_type == "float":
                        read_back_value_str = str(self.pm.get_value_float(prop_name))
                    elif value_type == "bool":
                        read_back_value_str = str(self.pm.get_value_bool(prop_name))
                    elif value_type == "enum":
                        read_back_value_str = self.pm.get_value_str(
                            prop_name
                        )  # Read as string

                    log.info(
                        f"Successfully set {prop_name} to {value}. Read back: {read_back_value_str}"
                    )
                else:
                    current_val_str = "N/A"
                    try:
                        current_val_str = prop_item.value_to_str()
                    except:
                        pass
                    log.warning(
                        f"{prop_name} property found but is not writable. Current value: {current_val_str}"
                    )
            else:
                log.warning(f"{prop_name} property not found.")
        except ic4.IC4Exception as e_prop:
            log.error(
                f"IC4Exception setting {prop_name} to {value}: {e_prop} (Code: {e_prop.code})"
            )
        except Exception as e_gen:
            log.error(f"Generic exception setting {prop_name} to {value}: {e_gen}")

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
                            f"Found device matching identifier '{self.device_identifier}': Model='{current_model_name}', Serial='{current_serial}', UniqueName='{current_unique_name}'"
                        )
                        break
                if not target_device_info:
                    raise RuntimeError(
                        f"Camera with identifier '{self.device_identifier}' not found among available devices."
                    )
            elif all_devices:
                target_device_info = all_devices[0]
                log.info(
                    f"No specific device identifier provided. Using first available device: {target_device_info.model_name}"
                )
            else:
                raise RuntimeError(
                    "No camera devices available and no identifier specified."
                )

            log.info(
                f"SDKCameraThread attempting to open: {target_device_info.model_name} (Using identifier: {self.device_identifier or 'first available'})"
            )
            self.grabber = ic4.Grabber()
            self.grabber.device_open(target_device_info)
            self.pm = self.grabber.device_property_map
            log.info(
                f"Device {target_device_info.model_name} opened. PropertyMap acquired."
            )

            # --- ATTEMPT TO SET A LOWER RESOLUTION AND PIXELFORMAT ---
            log.info(
                "Attempting to configure basic camera properties (PixelFormat, Resolution)..."
            )
            self._try_set_property("PixelFormat", "Mono8", "enum")  # Ensure Mono8
            self._try_set_property("Width", 640, "int")
            self._try_set_property("Height", 480, "int")
            log.info("Finished attempt to configure basic camera properties.")
            # --- END OF PROPERTY SETTING ATTEMPT ---

            try:
                self.sink = ic4.QueueSink(listener=self.sink_listener)
                log.info("SDKCameraThread: QueueSink initialized with listener.")
            except Exception as e_sink:
                log.exception(f"Failed to initialize QueueSink: {e_sink}")
                self.camera_error.emit(
                    f"QueueSink initialization error: {e_sink}", "SINK_INIT_ERROR"
                )
                raise

            log.debug("SDKCameraThread: Calling stream_setup(self.sink)...")
            self.grabber.stream_setup(self.sink)
            log.info("SDKCameraThread: stream_setup call completed.")

            if not self.grabber.is_acquisition_active:
                log.warning(
                    "SDKCameraThread: Acquisition NOT active immediately after stream_setup. Attempting explicit acquisition_start()..."
                )
                self.grabber.acquisition_start()
                if not self.grabber.is_acquisition_active:
                    log.error(
                        "SDKCameraThread: Explicit acquisition_start() also FAILED."
                    )
                    raise RuntimeError(
                        "Failed to start camera acquisition after stream_setup and explicit start."
                    )
                else:
                    log.info("SDKCameraThread: Explicit acquisition_start() SUCCEEDED.")
            else:
                log.info(
                    "SDKCameraThread: Acquisition IS active immediately after stream_setup."
                )

            log.info(
                "SDKCameraThread: Stream setup and acquisition start confirmed. Pausing briefly before loop."
            )
            QThread.msleep(250)
            log.info(
                "SDKCameraThread: Pause complete. Proceeding to frame acquisition loop..."
            )

            while not self._stop_requested:
                buf = None
                try:
                    buf = self.sink.pop_output_buffer()
                    if buf:
                        log.debug(f"Successfully popped a buffer object: {type(buf)}")
                        arr = buf.numpy_wrap()
                        q_image_format = QImage.Format_Grayscale8
                        if arr.ndim == 3 and arr.shape[2] == 3:
                            q_image_format = QImage.Format_BGR888
                        elif arr.ndim == 2 or (arr.ndim == 3 and arr.shape[2] == 1):
                            q_image_format = QImage.Format_Grayscale8
                        else:
                            log.warning(
                                f"Unsupported numpy array shape for QImage: {arr.shape}. Skipping frame."
                            )
                            if buf:
                                buf.release()  # Release if we skip
                            continue
                        final_arr_for_qimage = arr
                        if (
                            arr.ndim == 3
                            and q_image_format == QImage.Format_Grayscale8
                            and arr.shape[2] == 1
                        ):
                            final_arr_for_qimage = arr[..., 0]
                        q_image = QImage(
                            final_arr_for_qimage.data,
                            final_arr_for_qimage.shape[1],
                            final_arr_for_qimage.shape[0],
                            final_arr_for_qimage.strides[0],
                            q_image_format,
                        )
                        self.frame_ready.emit(q_image.copy(), arr.copy())
                        buf.release()
                    else:
                        log.debug(
                            "pop_output_buffer returned None/falsy, no new frame. Checking stop request."
                        )
                        if self._stop_requested:
                            log.debug(
                                "Stop requested and buffer is None, exiting acquisition loop."
                            )
                            break
                        QThread.msleep(10)
                        continue
                except ic4.IC4Exception as e:
                    log.warning(
                        f"IC4Exception caught in acquisition loop: {e} (Code: {e.code})"
                    )
                    if e.code == ic4.ErrorCode.Timeout:
                        if self._stop_requested:
                            break
                            continue
                    elif e.code == ic4.ErrorCode.NoData:
                        if self._stop_requested:
                            break
                        QThread.msleep(5)
                        continue
                    else:
                        log.error(
                            f"Unhandled IC4Exception in acquisition loop, breaking: {e} (Code: {e.code})"
                        )
                        self.camera_error.emit(str(e), str(e.code))
                        break
                except AttributeError as ae:
                    log.error(
                        f"AttributeError in acquisition loop (likely on buffer object): {ae}"
                    )
                    self.camera_error.emit(str(ae), "ATTRIBUTE_ERROR_BUFFER")
                    if buf and hasattr(buf, "release"):
                        try:
                            buf.release()
                        except Exception as e_release:
                            log.error(
                                f"Error releasing buffer after AttributeError: {e_release}"
                            )
                    break
                except Exception as e_loop:
                    log.exception(
                        f"Generic exception in SDKCameraThread acquisition loop: {e_loop}"
                    )
                    self.camera_error.emit(str(e_loop), "GENERIC_LOOP_ERROR")
                    if buf and hasattr(buf, "release"):
                        try:
                            buf.release()
                        except Exception as e_release:
                            log.error(
                                f"Error releasing buffer after generic exception: {e_release}"
                            )
                    break
            log.info("SDKCameraThread: Exited acquisition loop.")

        except RuntimeError as e_rt:
            log.error(f"RuntimeError in SDKCameraThread.run: {e_rt}")
            self.camera_error.emit(str(e_rt), "RUNTIME_SETUP_ERROR")
        except (
            ic4.IC4Exception
        ) as e_ic4_setup:  # This is the outer exception handler for setup phase
            log.error(
                f"IC4Exception during setup phase in SDKCameraThread.run: {e_ic4_setup} (Code: {e_ic4_setup.code})"
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
                        log.debug(
                            "SDKCameraThread: Stopping acquisition in finally block..."
                        )
                        self.grabber.acquisition_stop()
                except Exception as e_acq_stop:
                    log.error(
                        f"Exception during acquisition_stop in finally: {e_acq_stop}"
                    )
                try:
                    if self.grabber.is_device_open:
                        log.debug("SDKCameraThread: Closing device in finally block...")
                        self.grabber.device_close()
                except Exception as e_dev_close:
                    log.error(
                        f"Exception during device_close in finally: {e_dev_close}"
                    )
            self.grabber = None
            self.pm = None
            log.info("SDKCameraThread: finished run method and performed cleanup.")

    def stop(self):
        log.info(f"SDKCameraThread.stop() called for device {self.device_identifier}.")
        self._stop_requested = True
        if self.isRunning():
            log.debug(
                f"Waiting for SDKCameraThread ({self.device_identifier}) to finish..."
            )
            if not self.wait(3000):
                log.warning(
                    f"SDKCameraThread for {self.device_identifier} did not exit gracefully, terminating."
                )
                self.terminate()
                self.wait(500)
            else:
                log.info(
                    f"SDKCameraThread ({self.device_identifier}) finished gracefully."
                )
        else:
            log.info(
                f"SDKCameraThread ({self.device_identifier}) was not running when stop() was called."
            )
        log.info(
            f"SDKCameraThread.stop() completed for device {self.device_identifier}."
        )
