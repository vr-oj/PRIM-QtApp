# sdk_camera_thread.py
import logging
import time
import ctypes
import imagingcontrol4 as ic4

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)

# GenICam property names
PROP_WIDTH = "Width"
PROP_HEIGHT = "Height"
PROP_PIXEL_FORMAT = "PixelFormat"
PROP_ACQUISITION_FRAME_RATE = "AcquisitionFrameRate"
PROP_ACQUISITION_MODE = "AcquisitionMode"
PROP_TRIGGER_MODE = "TriggerMode"
PROP_EXPOSURE_TIME = "ExposureTime"
PROP_EXPOSURE_AUTO = "ExposureAuto"
PROP_GAIN = "Gain"


class DummySinkListener:
    # Required by SnapSink for buffer strategy
    num_buffers_required_on_connect = 4
    num_buffers_allocation_threshold = 4
    num_buffers_free_threshold = 7
    num_buffers_alloc_on_connect = 8
    num_buffers_max = 10

    def sink_connected(self, sink, image_type, min_buffers_required):
        log.debug(f"Sink connected: {image_type}, MinBuffers={min_buffers_required}")
        return True

    def frames_queued(self, sink):
        pass

    def sink_disconnected(self, sink):
        log.debug("Sink disconnected")


class SDKCameraThread(QThread):
    frame_ready = pyqtSignal(QImage, object)
    camera_resolutions_available = pyqtSignal(list)
    camera_video_formats_available = pyqtSignal(list)
    camera_properties_updated = pyqtSignal(dict)
    camera_error = pyqtSignal(str, str)

    def __init__(
        self,
        device_info=None,
        target_fps: float = 20.0,
        desired_width: int = 2448,  # Default to a high-res, adjust as needed or via UI
        desired_height: int = 2048,
        parent=None,
    ):
        super().__init__(parent)
        self.device_info = device_info
        self.target_fps = float(target_fps)  # Ensure it's float
        self.desired_width = int(desired_width)
        self.desired_height = int(desired_height)
        self._stop = False
        self.grabber = None
        self.sink = None
        self.pm = None  # PropertyMap
        self.listener = DummySinkListener()

    def request_stop(self):
        self._stop = True

    def _safe_init(self):
        try:
            ic4.Library.init()
        except RuntimeError:  # Or ic4.IC4Exception if specific
            pass  # Already initialized is fine
        except ic4.IC4Exception:  # Catch specific library exception
            pass

    def _set(self, name, val):
        if not self.pm:
            log.error(f"PropertyMap (self.pm) not initialized. Cannot set {name}.")
            return False  # Indicate failure

        prop = self.pm.find(name)
        if not prop:
            log.warning(f"Property '{name}' not found.")
            return False
        if not prop.is_available:
            log.warning(f"Property '{name}' is not available.")
            return False

        if prop.is_readonly:
            # Allow setting for specific known-updatable properties usually related to live adjustments
            if name not in (PROP_EXPOSURE_TIME, PROP_GAIN, PROP_EXPOSURE_AUTO):
                log.warning(
                    f"Skipping read-only property '{name}' during setup. Current value: {prop.value if hasattr(prop, 'value') else 'N/A'}"
                )
                return False  # Do not proceed for read-only setup properties
            # If it IS Exposure/Gain/Auto, we might proceed if it's a pseudo read-only (e.g. auto mode is on)
            # but for this function's primary use (setup), a true read-only should be skipped.

        try:
            current_value_str = "N/A"
            if isinstance(
                prop,
                (
                    ic4.PropertyInteger,
                    ic4.PropertyFloat,
                    ic4.PropertyBoolean,
                    ic4.PropertyString,
                ),
            ):
                current_value_str = "N/A"
            # Use correct property type names from ic4 library
            if isinstance(
                prop, (ic4.PropInteger, ic4.PropFloat, ic4.PropBoolean, ic4.PropString)
            ):
                current_value_str = str(prop.value)
            elif isinstance(prop, ic4.PropEnumeration):
                selected_entry = prop.selected_entry
                if selected_entry:
                    current_value_str = selected_entry.name

            log.debug(
                f"Attempting to set '{name}': Current='{current_value_str}', Target='{val}'"
            )

            if isinstance(prop, ic4.PropEnumeration):  # Corrected
                entry_to_set = None
                for entry in prop.entries:
                    if entry.name == str(val):
                        entry_to_set = entry
                        break
                if entry_to_set:
                    prop.selected_entry = entry_to_set
                else:
                    available_entries = [e.name for e in prop.entries]
                    log.error(
                        f"Failed to set enum '{name}': value '{val}' not found. Available: {available_entries}"
                    )
                    return False
            elif isinstance(prop, ic4.PropInteger):  # Corrected
                prop.value = int(val)
            elif isinstance(prop, ic4.PropFloat):  # Corrected
                prop.value = float(val)
            elif isinstance(prop, ic4.PropBoolean):  # Corrected
                prop.value = bool(val)
            elif isinstance(prop, ic4.PropString):  # Corrected
                prop.value = str(val)
            else:  # Command or other types not directly settable via .value
                log.warning(
                    f"Property '{name}' is of a type not directly settable by this _set method: {type(prop)}"
                )
                # For commands, it would be prop.execute() - not handled here.
                return False

            log.info(f"Successfully set '{name}' -> {val}")
            self.camera_properties_updated.emit({name: val})
            return True
        except ic4.IC4Exception as e:
            log.error(
                f"IC4Exception when setting '{name}' to '{val}': {e} (Code: {e.code}, Description: {e.description})"
            )
        except Exception as e:
            log.exception(f"Generic exception when setting '{name}' to '{val}'")
        return False

    def update_exposure(self, exposure_us: int):
        # If auto exposure is on, trying to set exposure time might fail or be ignored.
        # It's often necessary to turn auto exposure off first.
        current_auto_exposure = self.pm.find(PROP_EXPOSURE_AUTO)
        if current_auto_exposure and current_auto_exposure.is_available:
            if isinstance(current_auto_exposure, ic4.PropertyEnumeration):
                if current_auto_exposure.selected_entry.name != "Off":
                    log.info("Turning ExposureAuto Off before setting ExposureTime.")
                    self._set(
                        PROP_EXPOSURE_AUTO, "Off"
                    )  # Assuming "Off" is the correct enum string
            elif isinstance(
                current_auto_exposure, ic4.PropertyBoolean
            ):  # Some older APIs might use boolean
                if current_auto_exposure.value:
                    log.info(
                        "Turning ExposureAuto Off (boolean) before setting ExposureTime."
                    )
                    self._set(PROP_EXPOSURE_AUTO, False)

        self._set(PROP_EXPOSURE_TIME, exposure_us)

    def update_gain(self, gain_db: float):
        # Similar to exposure, ensure auto gain (if it exists and is separate) is off
        # For simplicity, assuming gain is not affected by ExposureAuto here, but it can be.
        self._set(PROP_GAIN, gain_db)

    def update_auto_exposure(self, enable_auto: bool):
        prop = self.pm.find(PROP_EXPOSURE_AUTO)
        if not prop or not prop.is_available:
            log.warning(f"Property '{PROP_EXPOSURE_AUTO}' not available for camera.")
            return

        target_value = None
        if isinstance(prop, ic4.PropertyEnumeration):
            entries = [e.name for e in getattr(prop, "entries", [])]
            if enable_auto:
                # Common names for continuous auto exposure. Adjust if your camera uses different ones.
                continuous_options = ["Continuous", "Auto"]
                target_value = next(
                    (opt for opt in continuous_options if opt in entries), None
                )
            else:
                if "Off" in entries:
                    target_value = "Off"

            if target_value is None:
                log.warning(
                    f"Could not find suitable enum value for {PROP_EXPOSURE_AUTO} enable={enable_auto}. Available: {entries}"
                )
                return

        elif isinstance(prop, ic4.PropertyBoolean):  # If it's a simple boolean property
            target_value = enable_auto
        else:
            log.warning(
                f"Unsupported property type for {PROP_EXPOSURE_AUTO}: {type(prop)}"
            )
            return

        self._set(PROP_EXPOSURE_AUTO, target_value)

    def run(self):
        self._safe_init()
        self.grabber = ic4.Grabber()
        try:
            self.grabber.set_timeout(10000)  # Increased timeout for grabber operations
        except AttributeError:  # Fallback for older ic4py versions
            self.grabber.timeout = 10000

        try:
            if not self.device_info:
                devices = ic4.DeviceEnum.devices()
                if not devices:
                    log.error("SDKCameraThread: No cameras found.")
                    self.camera_error.emit("No cameras found", "NoDevice")
                    return
                self.device_info = devices[0]  # Default to first camera

            log.info(
                f"SDKCameraThread: Opening device '{self.device_info.model_name}' (SN: {self.device_info.serial})"
            )
            self.grabber.device_open(self.device_info)
            self.pm = self.grabber.device_property_map  # Initialize self.pm here
            log.info(
                f"SDKCameraThread: Device '{self.device_info.model_name}' opened successfully."
            )

            # == Crucial Camera Configuration ==
            log.info(
                "SDKCameraThread: Configuring camera properties before streaming..."
            )

            # 1. Set TriggerMode to Off for free-running
            if not self._set(PROP_TRIGGER_MODE, "Off"):
                log.error(
                    f"Failed to set TriggerMode to Off. Acquisition may fail if camera expects triggers."
                )
                # Depending on strictness, you might want to emit an error and return here.
                # For now, we'll log and proceed, but this is a high-risk failure point.

            # 2. Set AcquisitionMode to Continuous
            self._set(PROP_ACQUISITION_MODE, "Continuous")

            # 3. Set PixelFormat
            #    IMPORTANT: Verify "Mono8" is supported and desired.
            #    Alternatives: "BGR8Packed" or "RGB8Packed" for color if QImage.Format_RGB888 is used.
            #    Use a tool like IC Capture to find your camera's exact pixel format names.
            self._set(PROP_PIXEL_FORMAT, "Mono8")

            # 4. Set Width and Height
            self._set(PROP_WIDTH, self.desired_width)
            self._set(PROP_HEIGHT, self.desired_height)

            # 5. Set AcquisitionFrameRate (optional, camera might have its own limits)
            #    Some cameras require AcquisitionFrameRateEnable to be true first.
            #    This is a simplified attempt.
            # 5. Set AcquisitionFrameRate
            log.debug(f"Attempting to find property 'AcquisitionFrameRateEnable'")
            prop_fps_enable = self.pm.find("AcquisitionFrameRateEnable")
            if prop_fps_enable:
                log.debug(
                    f"'AcquisitionFrameRateEnable' found. Available: {prop_fps_enable.is_available}, ReadOnly: {prop_fps_enable.is_readonly}"
                )
                if prop_fps_enable.is_available and not prop_fps_enable.is_readonly:
                    # Assuming it's an enumeration with "On"/"Off" or a boolean
                    if isinstance(
                        prop_fps_enable, ic4.PropEnumeration
                    ):  # Corrected type
                        if (
                            prop_fps_enable.selected_entry.name != "On"
                        ):  # Example target value
                            self._set("AcquisitionFrameRateEnable", "On")
                    elif isinstance(prop_fps_enable, ic4.PropBoolean):  # Corrected type
                        if not prop_fps_enable.value:
                            self._set("AcquisitionFrameRateEnable", True)
                    else:
                        log.warning(
                            f"'AcquisitionFrameRateEnable' is of unexpected type: {type(prop_fps_enable)}"
                        )
            else:
                log.warning(
                    "'AcquisitionFrameRateEnable' property not found. Proceeding without setting it."
                )

            self._set(PROP_ACQUISITION_FRAME_RATE, self.target_fps)
            log.info("SDKCameraThread: Camera configuration attempt finished.")
            # == End of Camera Configuration ==

            self.listener = DummySinkListener()
            self.sink = ic4.SnapSink(self.listener)
            log.info("SDKCameraThread: SnapSink created.")

            self.grabber.stream_setup(self.sink)
            log.info("SDKCameraThread: Stream setup complete.")

            self.grabber.acquisition_start()
            log.info("SDKCameraThread: Streaming started (acquisition_start called).")

            frame_count = 0
            start_time = time.time()

            while not self._stop:
                try:
                    buf = self.sink.pop_output_buffer(
                        timeout_ms=100
                    )  # Add timeout to prevent hard lock
                    if buf is None:  # Timeout occurred
                        continue

                    frame_count += 1
                    if frame_count % 100 == 0:  # Log stats periodically
                        elapsed_time = time.time() - start_time
                        current_fps = (
                            frame_count / elapsed_time if elapsed_time > 0 else 0
                        )
                        log.debug(
                            f"Grabbed 100 frames. Total: {frame_count}. Current ingest FPS: {current_fps:.2f}"
                        )

                    w, h = buf.image_type.width, buf.image_type.height
                    pf_name = (
                        buf.image_type.pixel_format.name
                    )  # Get pixel format name as string

                    # Determine QImage format based on camera's pixel format
                    qimage_format = None
                    if "Mono8" == pf_name:
                        qimage_format = QImage.Format_Grayscale8
                    elif pf_name in ("BGR8", "BGR8Packed"):  # Common for color cameras
                        qimage_format = (
                            QImage.Format_RGB888
                        )  # Data is BGR, QImage interprets as RGB if bytes are BGR
                    elif pf_name in ("RGB8", "RGB8Packed"):
                        qimage_format = (
                            QImage.Format_RGB888
                        )  # Data is RGB, QImage interprets as RGB
                    # Add more pixel format mappings as needed (e.g., Mono10, Mono12, YUV formats etc.)
                    # For formats like Mono10/12, you'd need to process the raw data into 8-bit for display
                    # or use a QImage format that supports higher bit depths if your Qt version does.

                    if qimage_format is None:
                        log.warning(
                            f"Unsupported pixel format for QImage conversion: {pf_name}. Skipping frame."
                        )
                        continue

                    # Extract bytes
                    # Modern ic4py versions provide numpy_wrap or direct pointer access
                    image_data = None
                    stride = 0
                    if hasattr(buf, "numpy_wrap"):  # Preferred method if available
                        arr = buf.numpy_wrap()
                        # For RGB8Packed/BGR8Packed, numpy_wrap usually gives correct shape.
                        # For Mono8, it's (h, w).
                        # Ensure data is contiguous for QImage if creating from numpy array directly (though we use bytes)
                        image_data = arr.tobytes()
                        stride = (
                            arr.strides[0]
                            if len(arr.strides) > 0
                            else w * buf.image_type.bytes_per_pixel
                        )

                    else:  # Fallback to raw pointer if numpy_wrap is not there
                        bytes_per_pixel = buf.image_type.bytes_per_pixel
                        # Pitch can sometimes be different from w * bpp due to alignment
                        pitch = getattr(buf, "pitch", w * bytes_per_pixel)
                        stride = pitch
                        # Size of buffer: pitch * h
                        buffer_size = pitch * h
                        image_data = ctypes.string_at(buf.pointer, buffer_size)

                    # Create QImage
                    # For RGB8/BGR8, QImage.Format_RGB888 expects data in RGB order usually.
                    # If pf_name is "BGR8", the bytes are B,G,R. QImage(data, w, h, stride, QImage.Format_RGB888)
                    # might display colors swapped if it expects R,G,B.
                    # A common trick for BGR data with Format_RGB888 is that it often works out if the
                    # underlying system also expects BGR (like OpenCV on Windows).
                    # If colors are swapped, you might need img.rgbSwapped() or manual byte reordering.

                    img = QImage(image_data, w, h, stride, qimage_format)

                    if (
                        pf_name in ("BGR8", "BGR8Packed")
                        and qimage_format == QImage.Format_RGB888
                    ):
                        # If the source is BGR and QImage took it as RGB, it might be displayed with swapped R and B.
                        # img = img.rgbSwapped() # Uncomment if Red and Blue are swapped in display
                        pass

                    if not img.isNull():
                        # Emit a copy, as the buffer 'buf' will be requeued.
                        # QImage uses implicit sharing, so a copy is often cheap unless modified.
                        # To be absolutely safe if 'img' or 'image_data' might be changed by another thread
                        # before it's processed, ensure a deep copy of the QImage or its data.
                        # For now, emitting the QImage directly.
                        self.frame_ready.emit(
                            img.copy(), image_data
                        )  # Emit a copy of QImage for safety
                    else:
                        log.warning(
                            f"Failed to create QImage from buffer. w={w},h={h},pf={pf_name}"
                        )

                    # buf.unlock() # Or similar if SnapSink requires manual unlocking; often automatic

                except ic4.IC4Exception as e:
                    if (
                        e.code == ic4.ErrorCode.Timeout
                    ):  # Expected if no new frame is ready
                        time.sleep(0.005)  # Short sleep on timeout
                        continue
                    log.error(
                        f"Acquisition loop IC4Exception: {str(e)} (Code: {e.code})"
                    )
                    # Decide if we need to stop on other IC4 errors
                    # self._stop = True # Example: stop on other errors
                    time.sleep(0.01)  # Brief pause
                except Exception as e_loop:
                    log.exception(f"Unexpected error in acquisition loop: {e_loop}")
                    self._stop = True  # Stop on unexpected errors

        except ic4.IC4Exception as e:  # Catch exceptions from setup phase
            error_message = str(e)
            log.error(
                f"Camera thread setup IC4Exception: {error_message} (Code: {e.code if hasattr(e, 'code') else 'N/A'})"
            )
            self.camera_error.emit(
                f"{error_message}", "IC4Exception"
            )  # Emit the full string representation
        except RuntimeError as e:  # Catch RuntimeError (e.g. "No cameras found")
            log.error(f"Camera thread setup RuntimeError: {str(e)}")
            self.camera_error.emit(str(e), "RuntimeError")
        except Exception as e:  # Catch all other exceptions during setup
            log.exception("Camera thread setup generic error")  # Log full traceback
            self.camera_error.emit(str(e), type(e).__name__)
        finally:
            log.info(
                f"SDKCameraThread: Entering finally block. is_streaming: {self.grabber.is_streaming if self.grabber else 'N/A'}"
            )
            if self.grabber:
                try:
                    if self.grabber.is_streaming:
                        log.info("SDKCameraThread: Stopping stream...")
                        self.grabber.stream_stop()
                        log.info("SDKCameraThread: Stream stopped.")
                except Exception as e_stop:
                    log.exception(f"Exception during stream_stop: {e_stop}")
                try:
                    if self.grabber.is_device_open:
                        log.info("SDKCameraThread: Closing device...")
                        self.grabber.device_close()
                        log.info("SDKCameraThread: Device closed.")
                except Exception as e_close:
                    log.exception(f"Exception during device_close: {e_close}")
            log.info("SDKCameraThread: Thread run method finished.")
