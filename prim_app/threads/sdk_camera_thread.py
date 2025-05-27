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

    def apply_node_settings(self, settings: dict):
        # This method is still bypassed in the simplified flow from MainWindow
        # but could be used if we re-enable CameraControlPanel later.
        if not self.pm or not self.grabber or not self.grabber.is_device_open:
            log.warning(
                "apply_node_settings called but property map or grabber not ready."
            )
            return

        log.debug(f"SDKCameraThread: Attempting to apply settings: {settings}")
        for feature_name, value in settings.items():
            try:
                # Example: self.pm.set_value("ExposureTime", value) if feature_name == "ExposureTime"
                # This would need more robust type handling and feature name mapping.
                # For now, keeping it simple as it's not actively called in simplified mode.
                log.info(
                    f"Setting {feature_name} to {value} (actual implementation pending)."
                )
                # self.pm.set_value(feature_name, value) # Example
            except Exception as e:
                log.error(f"Error applying setting {feature_name}={value}: {e}")
        pass  # Current simplified mode doesn't use this actively from UI

    def run(self):
        try:
            all_devices = ic4.DeviceEnum.devices()
            if not all_devices:
                raise RuntimeError("No camera devices found by IC4 DeviceEnum")

            target_device_info = None
            # ... (device discovery logic remains the same as your last version) ...
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

            # --- ATTEMPT TO SET A LOWER RESOLUTION ---
            try:
                # Let's try a common low resolution, e.g., 640x480
                # Other options: 800x600, 1280x720. Ensure camera supports it.
                # The DMK 33UX250 has a max of 2448x2048.
                new_width = 640
                new_height = 480
                log.info(
                    f"Attempting to set target resolution to {new_width}x{new_height}..."
                )

                # PixelFormat: Default seems to be Mono8, which is good. Let's ensure it if possible.
                try:
                    pixel_format_prop = self.pm.find("PixelFormat")
                    if pixel_format_prop and pixel_format_prop.is_writable:
                        # Attempt to set to Mono8 if not already
                        # current_pf_val = pixel_format_prop.value # This gets the enum member
                        # if current_pf_val != ic4.PixelFormat.Mono8:
                        self.pm.set_value("PixelFormat", ic4.PixelFormat.Mono8)
                        log.info(
                            f"PixelFormat set/confirmed to: {self.pm.get_value_str('PixelFormat')}"
                        )
                    elif pixel_format_prop:
                        log.info(
                            f"PixelFormat is {pixel_format_prop.value_to_str()}, not writable."
                        )
                    else:
                        log.warning("PixelFormat property not found.")
                except Exception as e_pf:
                    log.error(f"Error handling PixelFormat: {e_pf}")

                # Set Width
                width_prop = self.pm.find("Width")
                if width_prop and width_prop.is_writable:
                    # You could add checks here: if new_width >= width_prop.min and new_width <= width_prop.max
                    # And respect width_prop.increment if necessary for this camera.
                    # For simplicity, we'll try setting it directly.
                    self.pm.set_value("Width", new_width)
                    log.info(
                        f"Set Width to {new_width}. Read back: {self.pm.get_value_int('Width')}"
                    )
                elif width_prop:
                    log.warning(
                        f"Width property found but not writable. Current: {width_prop.value}"
                    )
                else:
                    log.warning("Width property not found.")

                # Set Height
                height_prop = self.pm.find("Height")
                if height_prop and height_prop.is_writable:
                    self.pm.set_value("Height", new_height)
                    log.info(
                        f"Set Height to {new_height}. Read back: {self.pm.get_value_int('Height')}"
                    )
                elif height_prop:
                    log.warning(
                        f"Height property found but not writable. Current: {height_prop.value}"
                    )
                else:
                    log.warning("Height property not found.")

                log.info("Finished attempt to set resolution.")

            except ic4.IC4Exception as e_res:
                log.error(
                    f"IC4Exception while trying to set resolution: {e_res} (Code: {e_res.code})"
                )
                log.warning("Continuing with current camera resolution due to error.")
            except Exception as e_gen_res:
                log.error(
                    f"Generic exception while trying to set resolution: {e_gen_res}"
                )
                log.warning("Continuing with current camera resolution due to error.")
            # --- END OF RESOLUTION SETTING ATTEMPT ---

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
                            buf.release()
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
        except ic4.IC4Exception as e_ic4_setup:
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
