# PRIM-QTAPP/prim_app/threads/sdk_camera_thread.py
import re
import numpy as np
import logging
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

# utils.utils import to_prop_name # Not strictly needed if not applying settings or emitting detailed props
# For simplicity, we can comment it out or remove if apply_node_settings is a pass
# from utils.utils import to_prop_name # Keep for now, might be used by error reporting or future minimal props

log = logging.getLogger(__name__)


class MinimalSinkListener(ic4.QueueSinkListener):
    def __init__(self, owner_name="DefaultListener"):
        super().__init__()
        self.owner_name = owner_name
        log.debug(f"MinimalSinkListener '{self.owner_name}' created.")

    def frame_ready(self, sink: ic4.QueueSink, buffer: ic4.ImageBuffer, userdata: any):
        pass  # Frame processing is handled by popping buffer in the thread's loop

    def frames_queued(self, sink: ic4.QueueSink):  # REMOVE 'userdata'
        log.debug(
            f"Listener '{self.owner_name}': Frames queued for {sink}."
        )  # Optional: uncomment for debugging

    pass

    def sink_connected(
        self, sink: ic4.QueueSink, image_type_proposed: ic4.ImageType, userdata: any
    ) -> bool:
        log.debug(
            f"Listener '{self.owner_name}': Sink connected. Grabber proposed ImageType: {image_type_proposed}. Accepting."
        )
        # Accept the proposed image type by the grabber.
        # If you want to force a different type, you could try setting it on the sink here,
        # but it's usually best to let the grabber decide or configure it on the grabber/device properties.
        return True

    def sink_disconnected(self, sink: ic4.QueueSink):  # REMOVE 'userdata'
        log.debug(
            f"Listener '{self.owner_name}': Sink disconnected from {sink}."
        )  # Optional: log the sink
        pass

    def sink_property_changed(
        self, sink: ic4.QueueSink, property_name: str, userdata: any
    ):
        pass  # Not handling property changes from sink in this simplified version


# read_current function can be removed if not querying properties during run
# def read_current(pm: ic4.PropertyMap, feature_name_sfnc: str): ...


class SDKCameraThread(QThread):
    frame_ready = pyqtSignal(
        QImage, object
    )  # QImage (for Qt display), object (numpy array for processing/recording)
    # Remove signals related to specific properties if not used in simplified version
    # resolutions_updated = pyqtSignal(list)
    # pixel_formats_updated = pyqtSignal(list)
    # fps_range_updated = pyqtSignal(float, float)
    # exposure_range_updated = pyqtSignal(float, float)
    # gain_range_updated = pyqtSignal(float, float)
    # auto_exposure_updated = pyqtSignal(bool)
    # properties_updated = pyqtSignal(dict) # This might still be useful for very basic info if needed later
    camera_error = pyqtSignal(str, str)  # (error_message, error_code_str)

    def __init__(
        self, device_name=None, fps=10, parent=None
    ):  # fps is now informational, not actively set
        super().__init__(parent)
        self.device_identifier = (
            device_name  # Can be serial, unique_name, or model_name
        )
        self.target_fps = float(
            fps
        )  # Stored but not used to set camera FPS in simplified version
        self._stop_requested = False
        self.grabber = None
        self.pm = None  # PropertyMap, might still be useful for basic info or future enhancements
        self.sink_listener = MinimalSinkListener(
            f"SDKThreadListener_{self.device_identifier or 'default'}"
        )
        log.info(
            f"SDKCameraThread (Simplified) initialized for device_identifier: '{self.device_identifier}', target_fps (informational): {self.target_fps}"
        )

    def apply_node_settings(self, settings: dict):
        # In simplified mode, we don't apply settings from UI.
        # This function can be a no-op or log that it's being ignored.
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
                    # Robust identifier matching
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
                    ):  # Match by any means
                        target_device_info = dev_info
                        log.info(
                            f"Found device matching identifier '{self.device_identifier}': Model='{current_model_name}', Serial='{current_serial}', UniqueName='{current_unique_name}'"
                        )
                        break
                if not target_device_info:
                    # If identifier was specific but not found, this is an error.
                    # If identifier was a general model name and multiple exist, this logic picks the first.
                    raise RuntimeError(
                        f"Camera with identifier '{self.device_identifier}' not found among available devices."
                    )
            elif all_devices:  # No specific identifier, pick the first one
                target_device_info = all_devices[0]
                log.info(
                    f"No specific device identifier provided. Using first available device: {target_device_info.model_name}"
                )
            else:  # Should be caught by "not all_devices" earlier, but as a safeguard
                raise RuntimeError(
                    "No camera devices available and no identifier specified."
                )

            log.info(
                f"SDKCameraThread (Simplified) attempting to open: {target_device_info.model_name} (Using identifier: {self.device_identifier or 'first available'})"
            )
            self.grabber = ic4.Grabber()
            self.grabber.device_open(target_device_info)
            self.pm = (
                self.grabber.device_property_map
            )  # Get property map, though not actively used for setting now
            log.info(
                f"Device {target_device_info.model_name} opened. PropertyMap acquired (simplified mode, not setting properties)."
            )

            # --- REMOVED PROPERTY QUERYING AND SETTING FOR SIMPLIFIED VERSION ---
            # No query_property_details calls
            # No initial_props_to_read_sfnc
            # No attempt to set AcquisitionFrameRate (self.pm.set_value(fps_sfnc_name, self.target_fps))
            # The camera will stream with its current default settings.

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
                raise  # Critical error, cannot proceed

            log.debug("SDKCameraThread (Simplified): Setting up stream...")

            # Step 1: Prepare the stream (allocates buffers, etc.)
            # Uses default setup_option (usually StreamSetupOption.PREPARE_ACQUISITION or similar)
            self.grabber.stream_setup(self.sink)
            log.info(
                "SDKCameraThread (Simplified): Stream resources prepared via stream_setup. This may have also started acquisition."
            )

            # After stream_setup, check if acquisition is active.
            # The previous "Acquisition is already active" error suggests stream_setup starts it.
            if not self.grabber.is_acquisition_active:
                # This case would be unexpected if the "already active" error was consistent.
                # However, as a fallback, if it's NOT active, we can try one explicit start.
                log.warning(
                    "SDKCameraThread (Simplified): Acquisition not active after stream_setup. Attempting one explicit acquisition_start()..."
                )
                self.grabber.acquisition_start()

                # Final check
                if not self.grabber.is_acquisition_active:
                    log.error(
                        "SDKCameraThread (Simplified): Acquisition FAILED to start even after an explicit attempt (is_acquisition_active is false)."
                    )
                    raise RuntimeError(
                        "Failed to start camera acquisition: is_acquisition_active remains false after all attempts."
                    )
                else:
                    log.info(
                        "SDKCameraThread (Simplified): Explicit acquisition_start() succeeded. Acquisition is active."
                    )
            else:
                log.info(
                    "SDKCameraThread (Simplified): Acquisition was already active after stream_setup. Proceeding to frame grabbing loop."
                )

            # Step 3: Verify if acquisition actually started
            if not self.grabber.is_acquisition_active:
                log.error(
                    "SDKCameraThread (Simplified): Acquisition FAILED to start after explicit command (is_acquisition_active is false). The camera did not confirm it started streaming."
                )
                # This is a critical failure. It's possible acquisition_start() itself could timeout
                # and raise an exception (which would be caught by the existing IC4Exception handler).
                # If it doesn't raise but is_acquisition_active is false, it's also an error.
                raise RuntimeError(
                    "Failed to start camera acquisition: is_acquisition_active is false after explicit start command."
                )
            else:
                log.info(
                    "SDKCameraThread (Simplified): Stream setup complete and acquisition is confirmed active."
                )

            while not self._stop_requested:
                try:
                    # Pop buffer with a timeout to allow checking _stop_requested flag
                    buf = (
                        self.sink.pop_output_buffer()
                    )  # Call with no explicit arguments
                    if (
                        not buf
                    ):  # Timeout occurred, or other non-error reason for no buffer
                        if (
                            self._stop_requested
                        ):  # Check if stop was requested during timeout
                            log.debug("Stop requested, exiting acquisition loop.")
                            break
                        # QThread.msleep(10) # No buffer, brief pause before retrying (already handled by timeout)
                        continue

                    # Minimal buffer validation (optional, but good practice)
                    # if not buf.is_valid:
                    #    log.warning(
                    #        "Popped an invalid buffer. Releasing and continuing."
                    #    )
                    #    buf.release()
                    #    continue

                    # Access numpy array from buffer
                    arr = (
                        buf.numpy_wrap()
                    )  # This is a view, be careful with its lifetime

                    # --- QImage Conversion (same as your existing robust logic) ---
                    # Determine QImage format based on numpy array shape
                    q_image_format = QImage.Format_Grayscale8  # Default
                    if arr.ndim == 3 and arr.shape[2] == 3:  # e.g., HxWx3 (BGR)
                        q_image_format = (
                            QImage.Format_BGR888
                        )  # Common for OpenCV/IC4 BGR
                    elif arr.ndim == 2 or (
                        arr.ndim == 3 and arr.shape[2] == 1
                    ):  # HxW or HxWx1
                        q_image_format = QImage.Format_Grayscale8
                    else:
                        log.warning(
                            f"Unsupported numpy array shape for QImage: {arr.shape}. Skipping frame."
                        )
                        buf.release()
                        continue

                    # If grayscale and ndim is 3 (HxWx1), QImage needs 2D array for Format_Grayscale8
                    # Or ensure data pointer and strides are correctly handled.
                    # Your existing GLViewfinder handles numpy array directly, so QImage conversion here
                    # is mainly if MainWindow or other Qt widgets need it.
                    # For GLViewfinder, the raw `arr` is more direct.

                    final_arr_for_qimage = arr
                    if (
                        arr.ndim == 3
                        and q_image_format == QImage.Format_Grayscale8
                        and arr.shape[2] == 1
                    ):
                        final_arr_for_qimage = arr[
                            ..., 0
                        ]  # Make it HxW for Grayscale8 QImage

                    q_image = QImage(
                        final_arr_for_qimage.data,
                        final_arr_for_qimage.shape[1],  # width
                        final_arr_for_qimage.shape[0],  # height
                        final_arr_for_qimage.strides[0],  # bytes per line
                        q_image_format,
                    )
                    # Emit copies to avoid issues with buffer lifetime / QImage data ownership
                    self.frame_ready.emit(q_image.copy(), arr.copy())
                    buf.release()  # Crucial: release buffer back to the sink

                except ic4.IC4Exception as e:
                    if e.code == ic4.ErrorCode.Timeout:
                        # This is expected if pop_output_buffer times out
                        log.debug(
                            "pop_output_buffer timed out (IC4Exception). Continuing."
                        )
                        if self._stop_requested:
                            break  # Check again
                        continue
                    elif (
                        e.code == ic4.ErrorCode.NoData
                    ):  # Another non-fatal "no data yet"
                        log.debug("pop_output_buffer returned NoData. Continuing.")
                        if self._stop_requested:
                            break
                        QThread.msleep(5)  # Brief pause
                        continue
                    # For other IC4Exceptions, log as error and potentially stop
                    log.error(
                        f"IC4Exception in SDKCameraThread acquisition loop: {e} (Code: {e.code})"  # REMOVE .name
                    )
                    self.camera_error.emit(str(e), str(e.code))  # Emit error
                    break  # Exit loop on significant IC4 error
                except Exception as e_loop:  # Catch any other unexpected errors
                    log.exception(
                        f"Generic exception in SDKCameraThread acquisition loop: {e_loop}"
                    )
                    self.camera_error.emit(str(e_loop), "GENERIC_LOOP_ERROR")
                    break  # Exit loop
            log.info("SDKCameraThread (Simplified): Exited acquisition loop.")

        except (
            RuntimeError
        ) as e_rt:  # Errors during setup (e.g., no devices, device open fail)
            log.error(f"RuntimeError in SDKCameraThread.run (Simplified): {e_rt}")
            self.camera_error.emit(str(e_rt), "RUNTIME_SETUP_ERROR")
        except ic4.IC4Exception as e_ic4_setup:
            log.error(
                f"IC4Exception during setup in SDKCameraThread.run (Simplified): {e_ic4_setup} (Code: {e_ic4_setup.code})"  # REMOVE .name
            )
            self.camera_error.emit(str(e_ic4_setup), str(e_ic4_setup.code))
        except (
            Exception
        ) as ex_outer:  # Catch-all for any other unhandled exceptions in run()
            log.exception(
                f"Outer unhandled exception in SDKCameraThread.run (Simplified): {ex_outer}"
            )
            self.camera_error.emit(
                str(ex_outer),
                getattr(
                    ex_outer, "__class__", type(ex_outer)
                ).__name__,  # Get class name of exception
            )
        finally:
            log.debug(
                "SDKCameraThread.run() (Simplified) entering finally block for cleanup."
            )
            if self.grabber:
                try:
                    if self.grabber.is_acquisition_active:
                        log.debug(
                            "SDKCameraThread (Simplified): Stopping acquisition..."
                        )
                        self.grabber.acquisition_stop()
                except Exception as e_acq_stop:
                    log.error(
                        f"Exception during acquisition_stop in finally: {e_acq_stop}"
                    )
                try:
                    if self.grabber.is_device_open:
                        log.debug("SDKCameraThread (Simplified): Closing device...")
                        self.grabber.device_close()
                except Exception as e_dev_close:
                    log.error(
                        f"Exception during device_close in finally: {e_dev_close}"
                    )

            # Release other resources if any (e.g., self.sink, self.pm - usually managed by grabber/Python's GC)
            self.grabber = None
            self.pm = None
            # self.sink is managed by its listener or Python's GC when no longer referenced

            log.info(
                "SDKCameraThread (Simplified) finished run method and performed cleanup."
            )

    def stop(self):
        log.info(
            f"SDKCameraThread.stop() (Simplified) called for device {self.device_identifier}."
        )
        self._stop_requested = True  # Signal the run loop to exit

        # Wait for the thread to finish.
        # The timeout should be reasonably short if the loop checks _stop_requested frequently.
        if self.isRunning():
            log.debug(
                f"Waiting for SDKCameraThread ({self.device_identifier}) to finish..."
            )
            if not self.wait(3000):  # Wait for 3 seconds
                log.warning(
                    f"SDKCameraThread for {self.device_identifier} did not exit gracefully within timeout, terminating."
                )
                self.terminate()  # Forcefully terminate if wait fails
                self.wait(500)  # Brief wait for termination to process
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
