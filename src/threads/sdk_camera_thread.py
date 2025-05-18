import imagingcontrol4 as ic4
from imagingcontrol4.properties import (
    PropInteger,
)  # Import if you use it for property checking
from PyQt5.QtCore import QThread, pyqtSignal, QMutex, QWaitCondition
from PyQt5.QtGui import QImage
import logging
import time  # For potential sleeps or timing checks

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    # Emits: QImage (for preview), object (raw numpy array for recording)
    frame_ready = pyqtSignal(QImage, object)
    # Emits: error_message (str), error_code (int, or unique string)
    camera_error = pyqtSignal(str, str)  # Using string for error code for flexibility
    # Emits: list of resolution strings like ["640x480", "1920x1080"]
    # This might be better handled by QtCameraWidget after querying properties.
    # For now, this thread will focus on streaming.

    def __init__(self, exposure_us=20000, target_fps=20, parent=None):
        super().__init__(parent)
        self.exposure_us = exposure_us
        self.target_fps = target_fps
        # self._interval_ms = int(1000 / target_fps) if target_fps > 0 else 50 # snap_single has timeout
        self._running_mutex = QMutex()
        self._running = False
        self._stop_requested = False

        self.grabber = None
        self.sink = None
        self.device_info = None  # Store device info if needed later

        # Desired properties (can be overridden by specific camera logic or GUI controls)
        self.desired_width = 640
        self.desired_height = 480
        self.desired_pixel_format = "Mono8"  # Example, adjust as needed

    def is_running(self):
        self._running_mutex.lock()
        val = self._running
        self._running_mutex.unlock()
        return val

    def _set_running(self, val):
        self._running_mutex.lock()
        self._running = val
        self._running_mutex.unlock()

    def run(self):
        self._set_running(True)
        self._stop_requested = False
        log.info(
            f"SDKCameraThread started. Target FPS: {self.target_fps}, Exposure: {self.exposure_us}us"
        )

        local_grabber = None
        local_sink = None

        try:
            # 1. Enumerate devices (assuming the first one is the target)
            # More robust selection would involve passing a serial number or model.
            devices = ic4.DeviceEnum.devices()
            if not devices:
                log.error("No TIS cameras found by imagingcontrol4.")
                self.camera_error.emit("No TIS cameras found.", "NO_DEVICE_FOUND")
                self._set_running(False)
                return
            self.device_info = devices[0]  # Store for reference
            log.info(
                f"Attempting to use camera: {self.device_info.model_name} (S/N {self.device_info.serial})"
            )

            # 2. Open device
            local_grabber = ic4.Grabber()
            local_grabber.device_open(self.device_info)
            self.grabber = local_grabber  # Assign to self if needed for external access, ensure cleanup
            log.info(f"Device {self.device_info.model_name} opened.")

            # 3. Configure properties
            pm = local_grabber.device_property_map

            # Example: Acquisition Mode and Trigger
            for prop_id, val_str in (
                (ic4.PropId.ACQUISITION_MODE, "Continuous"),
                (ic4.PropId.TRIGGER_MODE, "Off"),
            ):
                try:
                    pm.set_value(prop_id, val_str)
                    log.debug(f"Set {prop_id.name} to {val_str}")
                except ic4.IC4Exception as e:
                    log.warning(f"Could not set {prop_id.name} to {val_str}: {e}")

            # Example: Set Frame Size, Pixel Format, Exposure
            # These should ideally come from GUI or config, or queried for validity
            try:
                current_format = pm.get_value_string(ic4.PropId.PIXEL_FORMAT)
                if current_format != self.desired_pixel_format:
                    pm.set_value(ic4.PropId.PIXEL_FORMAT, self.desired_pixel_format)
                    log.info(
                        f"Pixel format set to {self.desired_pixel_format} (was {current_format})"
                    )

                # Width and Height (ensure they are valid for the chosen pixel format)
                # Querying min/max/inc for width/height is good practice
                pm.set_value(ic4.PropId.WIDTH, self.desired_width)
                log.info(f"Width set to {self.desired_width}")
                pm.set_value(ic4.PropId.HEIGHT, self.desired_height)
                log.info(f"Height set to {self.desired_height}")

                pm.set_value(
                    ic4.PropId.EXPOSURE_TIME, self.exposure_us
                )  # Exposure in microseconds
                log.info(f"Exposure set to {self.exposure_us} us")

                # Optionally, set FPS if the camera supports it as a direct property
                # if pm.is_feature_available(ic4.PropId.ACQUISITION_FRAME_RATE_ENABLE):
                #     pm.set_value(ic4.PropId.ACQUISITION_FRAME_RATE_ENABLE, True)
                # if pm.is_feature_available(ic4.PropId.ACQUISITION_FRAME_RATE):
                #    pm.set_value_float(ic4.PropId.ACQUISITION_FRAME_RATE, float(self.target_fps))
                #    log.info(f"Target FPS set to {self.target_fps} on camera property.")

            except ic4.IC4Exception as e:
                log.error(f"Error setting core camera properties: {e}")
                self.camera_error.emit(f"Property Error: {e}", "PROPERTY_ERROR")
                local_grabber.device_close()
                self._set_running(False)
                return

            # 4. Setup Sink and Start Acquisition
            local_sink = ic4.SnapSink()
            self.sink = local_sink  # Assign for cleanup

            local_grabber.stream_setup(
                local_sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            log.info("Stream setup complete and acquisition started.")

            # 5. Acquisition Loop
            while not self._stop_requested:
                try:
                    # Timeout for snap_single is crucial.
                    # Should be slightly more than expected frame interval (1/FPS)
                    # Or a fixed reasonable value if FPS is high.
                    timeout_ms = (
                        int(1000 / self.target_fps * 2) if self.target_fps > 0 else 200
                    )
                    timeout_ms = max(timeout_ms, 100)  # Minimum timeout

                    img_buf = local_sink.snap_single(timeout_ms=timeout_ms)
                    raw_frame_numpy = (
                        img_buf.numpy_copy()
                    )  # This is the raw data (numpy array)

                    # Convert numpy array to QImage for preview
                    h, w = raw_frame_numpy.shape[:2]  # Works for mono and color

                    q_image = None
                    pixel_format_str = pm.get_value_string(
                        ic4.PropId.PIXEL_FORMAT
                    )  # Get current format

                    if pixel_format_str in [
                        "Mono8",
                        "Y800",
                    ]:  # Add other mono formats if needed
                        if (
                            raw_frame_numpy.ndim == 2
                            and raw_frame_numpy.dtype == "uint8"
                        ):
                            bytes_per_line = w
                            q_image = QImage(
                                raw_frame_numpy.data,
                                w,
                                h,
                                bytes_per_line,
                                QImage.Format_Grayscale8,
                            )
                        else:
                            log.warning(
                                f"Mono8/Y800 format reported, but numpy array shape/dtype mismatch: {raw_frame_numpy.shape}, {raw_frame_numpy.dtype}"
                            )
                    elif pixel_format_str in [
                        "RGB8",
                        "BGR8",
                    ]:  # Example for packed RGB/BGR
                        if (
                            raw_frame_numpy.ndim == 3
                            and raw_frame_numpy.shape[2] == 3
                            and raw_frame_numpy.dtype == "uint8"
                        ):
                            bytes_per_line = w * 3
                            # imagingcontrol4 usually provides data in the format specified (e.g. RGB8 is RGB)
                            # QImage.Format_RGB888 expects RGB order.
                            # If camera sends BGR8, you'd use Format_BGR888 or convert.
                            fmt = (
                                QImage.Format_RGB888
                                if pixel_format_str == "RGB8"
                                else QImage.Format_BGR888
                            )  # Requires Qt 5.10+ for BGR888
                            if (
                                pixel_format_str == "BGR8"
                                and QImage.Format_BGR888 is NotImplemented
                            ):  # Fallback for older Qt
                                temp_frame = ic4.bgr_to_rgb(
                                    raw_frame_numpy
                                )  # Requires ic4.Utils if available
                                q_image = QImage(
                                    temp_frame.data,
                                    w,
                                    h,
                                    bytes_per_line,
                                    QImage.Format_RGB888,
                                )
                            else:
                                q_image = QImage(
                                    raw_frame_numpy.data, w, h, bytes_per_line, fmt
                                )
                        else:
                            log.warning(
                                f"{pixel_format_str} format reported, but numpy array shape/dtype mismatch: {raw_frame_numpy.shape}, {raw_frame_numpy.dtype}"
                            )
                    # Add more elif blocks for other formats like Bayer (would need debayering), YUV, Mono10/12/16 (would need scaling/conversion)
                    else:
                        log.warning(
                            f"Unsupported pixel format for QImage conversion: {pixel_format_str}. Frame shape: {raw_frame_numpy.shape}"
                        )

                    if q_image and not q_image.isNull():
                        # IMPORTANT: Emit copies if data is to be used across threads or asynchronously
                        self.frame_ready.emit(q_image.copy(), raw_frame_numpy.copy())

                    del img_buf  # Explicitly release the buffer

                except ic4.IC4Exception as e_snap:
                    if e_snap.code == ic4.ErrorCode.Timeout:
                        log.debug(
                            "Snap operation timed out (normal if waiting for frame or if FPS is low)."
                        )
                        # If stop is requested, break immediately
                        if self._stop_requested:
                            log.info("Stop requested during snap timeout.")
                            break
                        # Optional: short sleep to prevent busy-looping on continuous timeouts
                        # self.msleep(10)
                        continue  # Try to snap again
                    else:
                        log.error(
                            f"imagingcontrol4 error during snap_single: {e_snap.code} - {e_snap}",
                            exc_info=False,
                        )
                        self.camera_error.emit(
                            f"Snap Error: {e_snap.message}", str(e_snap.code)
                        )
                        break  # Exit loop on other ic4 errors
                except Exception as e_loop:
                    log.exception(
                        f"Unexpected error in SDKCameraThread acquisition loop: {e_loop}"
                    )
                    self.camera_error.emit(
                        f"Loop Error: {str(e_loop)}", "UNEXPECTED_LOOP_ERROR"
                    )
                    break  # Exit loop

        except ic4.IC4Exception as e_setup:
            log.error(
                f"imagingcontrol4 error during camera setup: {e_setup.code} - {e_setup}",
                exc_info=False,
            )
            self.camera_error.emit(f"Setup Error: {e_setup.message}", str(e_setup.code))
        except Exception as e_outer:
            log.exception(
                f"Critical unexpected error in SDKCameraThread run method: {e_outer}"
            )
            self.camera_error.emit(
                f"Critical Error: {str(e_outer)}", "CRITICAL_THREAD_ERROR"
            )
        finally:
            log.info("SDKCameraThread run method finishing. Cleaning up resources...")
            if local_grabber is not None:
                if local_grabber.is_streaming():
                    try:
                        log.info("Stopping stream...")
                        local_grabber.stream_stop()
                    except ic4.IC4Exception as e:
                        log.error(f"Error stopping stream: {e}")
                if local_grabber.is_device_open():
                    try:
                        log.info("Closing device...")
                        local_grabber.device_close()
                    except ic4.IC4Exception as e:
                        log.error(f"Error closing device: {e}")

            self.grabber = None  # Clear self references
            self.sink = None
            self.device_info = None

            self._set_running(False)
            log.info("SDKCameraThread finished.")

    def stop(self):
        log.info("SDKCameraThread: stop() method called.")
        self._running_mutex.lock()  # Ensure consistent access to _stop_requested
        self._stop_requested = True
        self._running_mutex.unlock()
        # Do not call self.wait() here from an external thread if this thread might be
        # blocked in native code. Rely on the run() loop to check _stop_requested
        # and terminate. The QThread's default termination behavior or explicit
        # QThread.quit() and QThread.wait() from the managing thread (e.g., in QtCameraWidget)
        # is generally safer.
