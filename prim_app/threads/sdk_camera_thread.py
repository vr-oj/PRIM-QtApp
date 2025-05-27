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

    def frames_queued(self, sink: ic4.QueueSink):  # MODIFIED: Removed 'userdata'
        # log.debug(f"Listener '{self.owner_name}': Frames queued for {sink}.")
        pass

    def sink_connected(
        self, sink: ic4.QueueSink, image_type_proposed: ic4.ImageType, userdata: any
    ) -> bool:
        log.debug(
            f"Listener '{self.owner_name}': Sink connected. Grabber proposed ImageType: {image_type_proposed}. Accepting."
        )
        return True

    def sink_disconnected(self, sink: ic4.QueueSink):  # MODIFIED: Removed 'userdata'
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
        log.debug(
            f"SDKCameraThread (Simplified): apply_node_settings called with {settings}, but will be ignored in simplified mode."
        )
        pass

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
                f"SDKCameraThread (Simplified) attempting to open: {target_device_info.model_name} (Using identifier: {self.device_identifier or 'first available'})"
            )
            self.grabber = ic4.Grabber()
            self.grabber.device_open(target_device_info)
            self.pm = self.grabber.device_property_map
            log.info(
                f"Device {target_device_info.model_name} opened. PropertyMap acquired (simplified mode, not setting properties)."
            )

            try:
                self.sink = ic4.QueueSink(listener=self.sink_listener)
                log.info(
                    "SDKCameraThread (Simplified): QueueSink initialized with listener."
                )
            except Exception as e_sink:
                log.exception(f"Failed to initialize QueueSink: {e_sink}")
                self.camera_error.emit(
                    f"QueueSink initialization error: {e_sink}", "SINK_INIT_ERROR"
                )
                raise

            log.debug(
                "SDKCameraThread (Simplified): Calling stream_setup(self.sink)..."
            )
            self.grabber.stream_setup(self.sink)  # Let this do its work.
            log.info("SDKCameraThread (Simplified): stream_setup call completed.")

            # CRUCIAL CHECK: Immediately after stream_setup
            if not self.grabber.is_acquisition_active:
                log.warning(
                    "SDKCameraThread (Simplified): Acquisition NOT active immediately after stream_setup. Attempting explicit acquisition_start()..."
                )
                self.grabber.acquisition_start()  # Try to explicitly start it
                if not self.grabber.is_acquisition_active:
                    log.error(
                        "SDKCameraThread (Simplified): Explicit acquisition_start() also FAILED."
                    )
                    raise RuntimeError(
                        "Failed to start camera acquisition after stream_setup and explicit start."
                    )
                else:
                    log.info(
                        "SDKCameraThread (Simplified): Explicit acquisition_start() SUCCEEDED."
                    )
            else:
                log.info(
                    "SDKCameraThread (Simplified): Acquisition IS active immediately after stream_setup."
                )

            log.info(
                "SDKCameraThread (Simplified): Proceeding to frame acquisition loop..."
            )
            # QThread.msleep(100) # Optional: small delay before loop, likely not needed now

            while not self._stop_requested:
                buf = None  # Initialize buf
                try:
                    buf = (
                        self.sink.pop_output_buffer()
                    )  # Call with no explicit arguments

                    if buf:  # If a buffer object is returned
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
                        # pop_output_buffer returned None (or falsy) - indicates no data without an exception
                        # This path might be hit if stream stops cleanly and sink empties.
                        log.debug(
                            "pop_output_buffer returned None/falsy, no new frame. Checking stop request."
                        )
                        if self._stop_requested:
                            log.debug(
                                "Stop requested and buffer is None, exiting acquisition loop."
                            )
                            break
                        QThread.msleep(10)  # Brief pause if consistently no data
                        continue

                except ic4.IC4Exception as e:
                    # Log the specific IC4Exception code
                    log.warning(
                        f"IC4Exception caught in acquisition loop: {e} (Code: {e.code})"
                    )
                    if e.code == ic4.ErrorCode.Timeout:
                        # log.debug("Specifically a Timeout error in loop. Continuing.") # Already covered by general log
                        if self._stop_requested:
                            break
                        continue
                    elif e.code == ic4.ErrorCode.NoData:
                        # log.debug("Specifically a NoData error in loop. Continuing.") # Commented out as requested
                        if self._stop_requested:
                            break
                        QThread.msleep(5)
                        continue
                    else:
                        # Any other IC4Exception in the loop is considered significant
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
            log.info("SDKCameraThread (Simplified): Exited acquisition loop.")

        except RuntimeError as e_rt:
            log.error(f"RuntimeError in SDKCameraThread.run (Simplified): {e_rt}")
            self.camera_error.emit(str(e_rt), "RUNTIME_SETUP_ERROR")
        except ic4.IC4Exception as e_ic4_setup:
            log.error(
                f"IC4Exception during setup phase in SDKCameraThread.run (Simplified): {e_ic4_setup} (Code: {e_ic4_setup.code})"
            )
            self.camera_error.emit(str(e_ic4_setup), str(e_ic4_setup.code))
        except Exception as ex_outer:
            log.exception(
                f"Outer unhandled exception in SDKCameraThread.run (Simplified): {ex_outer}"
            )
            self.camera_error.emit(
                str(ex_outer), getattr(ex_outer, "__class__", type(ex_outer)).__name__
            )
        finally:
            log.debug(
                "SDKCameraThread.run() (Simplified) entering finally block for cleanup."
            )
            if self.grabber:
                try:
                    if self.grabber.is_acquisition_active:
                        log.debug(
                            "SDKCameraThread (Simplified): Stopping acquisition in finally block..."
                        )
                        self.grabber.acquisition_stop()
                except Exception as e_acq_stop:
                    log.error(
                        f"Exception during acquisition_stop in finally: {e_acq_stop}"
                    )
                try:
                    if self.grabber.is_device_open:
                        log.debug(
                            "SDKCameraThread (Simplified): Closing device in finally block..."
                        )
                        self.grabber.device_close()
                except Exception as e_dev_close:
                    log.error(
                        f"Exception during device_close in finally: {e_dev_close}"
                    )
            self.grabber = None
            self.pm = None
            log.info(
                "SDKCameraThread (Simplified) finished run method and performed cleanup."
            )

    def stop(self):
        log.info(
            f"SDKCameraThread.stop() (Simplified) called for device {self.device_identifier}."
        )
        self._stop_requested = True
        if self.isRunning():
            log.debug(
                f"Waiting for SDKCameraThread ({self.device_identifier}) to finish..."
            )
            if not self.wait(3000):
                log.warning(
                    f"SDKCameraThread for {self.device_identifier} did not exit gracefully within timeout, terminating."
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
            f"SDKCameraThread.stop() (Simplified) completed for device {self.device_identifier}."
        )
