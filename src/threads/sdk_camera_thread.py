# sdk_camera_thread.py
import logging
import time
import ctypes
import imagingcontrol4 as ic4

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)

# GenICam property names (keep these as they are)
PROP_WIDTH = "Width"
PROP_HEIGHT = "Height"
PROP_PIXEL_FORMAT = "PixelFormat"
PROP_ACQUISITION_FRAME_RATE = "AcquisitionFrameRate"
PROP_ACQUISITION_MODE = "AcquisitionMode"
PROP_TRIGGER_MODE = "TriggerMode"
PROP_EXPOSURE_TIME = "ExposureTime"
PROP_EXPOSURE_AUTO = "ExposureAuto"
PROP_GAIN = "Gain"


# Simplified DummySinkListener, similar to test_ic4.py
class DummySinkListener:
    def sink_connected(self, sink, image_type, min_buffers_required):
        log.debug(f"Sink connected: {image_type}, MinBuffers={min_buffers_required}")
        # For QueueSink, we typically just need to return True if we are ready.
        # The sink itself manages its buffers based on its internal strategy or defaults.
        return True

    def frames_queued(self, sink):
        # This callback indicates new frames are in the sink's queue.
        # In a polling model (pop_output_buffer), this might just be logged or used to wake a polling loop.
        pass

    def sink_disconnected(self, sink):
        log.debug("Sink disconnected")


from PyQt5.QtCore import pyqtSignal


class SDKCameraThread(QThread):
    camera_configured = pyqtSignal(object, object)  # emits (device, sink)
    frame_ready = pyqtSignal(QImage, object)
    camera_resolutions_available = pyqtSignal(list)
    camera_video_formats_available = pyqtSignal(list)
    camera_properties_updated = pyqtSignal(dict)
    camera_error = pyqtSignal(str, str)
    camera_configured = pyqtSignal(object, object)  # emits (device, sink)

    def __init__(
        self,
        device_info=None,
        target_fps: float = 20.0,
        desired_width: int = 2448,
        desired_height: int = 2048,
        parent=None,
    ):
        super().__init__(parent)
        self.device_info = device_info
        self.target_fps = float(target_fps)
        self.desired_width = int(desired_width)
        self.desired_height = int(desired_height)
        self._stop = False
        self.grabber = None
        self.sink = None
        self.pm = None
        self.listener = DummySinkListener()  # Use the simplified listener

    # ... (request_stop, _safe_init, _set, update_exposure, update_gain, update_auto_exposure methods remain the same as the last version) ...
    def request_stop(self):
        self._stop = True

    def _safe_init(self):
        try:
            ic4.Library.init()
        except (RuntimeError, ic4.IC4Exception):
            pass

    def _set(self, name, val):
        if not self.pm:
            log.error(f"PropertyMap (self.pm) not initialized. Cannot set {name}.")
            return False

        prop = self.pm.find(name)
        if not prop:
            log.warning(f"Property '{name}' not found.")
            return False
        if not prop.is_available:
            log.warning(f"Property '{name}' is not available.")
            return False

        if prop.is_readonly:
            if name not in (PROP_EXPOSURE_TIME, PROP_GAIN, PROP_EXPOSURE_AUTO):
                log.warning(
                    f"Skipping read-only property '{name}' during setup. Current value: {prop.value if hasattr(prop, 'value') else 'N/A'}"
                )
                return False

        try:
            current_value_str = "N/A"
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

            if isinstance(prop, ic4.PropEnumeration):
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
            elif isinstance(prop, ic4.PropInteger):
                prop.value = int(val)
            elif isinstance(prop, ic4.PropFloat):
                prop.value = float(val)
            elif isinstance(prop, ic4.PropBoolean):
                prop.value = bool(val)
            elif isinstance(prop, ic4.PropString):
                prop.value = str(val)
            else:
                log.warning(
                    f"Property '{name}' is of a type not directly settable by this _set method: {type(prop)}"
                )
                return False

            log.info(f"Successfully set '{name}' -> {val}")
            self.camera_properties_updated.emit({name: val})
            return True
        except ic4.IC4Exception as e:
            log.error(
                f"IC4Exception when setting '{name}' to '{val}': {str(e)} (Code: {e.code if hasattr(e, 'code') else 'N/A'})"
            )
        except Exception as e:
            log.exception(f"Generic exception when setting '{name}' to '{val}'")
        return False

    def update_exposure(self, exposure_us: int):
        current_auto_exposure = self.pm.find(PROP_EXPOSURE_AUTO)
        if current_auto_exposure and current_auto_exposure.is_available:
            if isinstance(current_auto_exposure, ic4.PropEnumeration):
                if (
                    current_auto_exposure.selected_entry
                    and current_auto_exposure.selected_entry.name != "Off"
                ):
                    log.info("Turning ExposureAuto Off before setting ExposureTime.")
                    self._set(PROP_EXPOSURE_AUTO, "Off")
            elif isinstance(current_auto_exposure, ic4.PropBoolean):
                if current_auto_exposure.value:
                    log.info(
                        "Turning ExposureAuto Off (boolean) before setting ExposureTime."
                    )
                    self._set(PROP_EXPOSURE_AUTO, False)

        self._set(PROP_EXPOSURE_TIME, exposure_us)

    def update_gain(self, gain_db: float):
        self._set(PROP_GAIN, gain_db)

    def update_auto_exposure(self, enable_auto: bool):
        prop = self.pm.find(PROP_EXPOSURE_AUTO)
        if not prop or not prop.is_available:
            log.warning(f"Property '{PROP_EXPOSURE_AUTO}' not available for camera.")
            return

        target_value = None
        if isinstance(prop, ic4.PropEnumeration):
            entries = [e.name for e in getattr(prop, "entries", [])]
            if enable_auto:
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
        elif isinstance(prop, ic4.PropBoolean):
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
        # --- ENSURE THESE LINES ARE COMMENTED OUT or REMOVED ---
        # try:
        #     self.grabber.set_timeout(20000)
        # except AttributeError:
        #     self.grabber.timeout = 20000
        # --- END OF SECTION TO ENSURE IS COMMENTED/REMOVED ---

        try:
            if not self.device_info:
                devices = ic4.DeviceEnum.devices()
                if not devices:
                    log.error("SDKCameraThread: No cameras found.")
                    self.camera_error.emit("No cameras found", "NoDevice")
                    return
                self.device_info = devices[0]

            log.info(
                f"SDKCameraThread: Opening device '{self.device_info.model_name}' (SN: {self.device_info.serial})"
            )
            self.grabber.device_open(self.device_info)
            self.pm = self.grabber.device_property_map
            self.device = self.grabber.device
            log.info(
                f"SDKCameraThread: Device '{self.device_info.model_name}' opened successfully."
            )

            log.info(
                "SDKCameraThread: Configuring camera properties before streaming..."
            )

            log.info("Setting PixelFormat, Width, Height first...")
            if not self._set(PROP_PIXEL_FORMAT, "Mono8"):
                log.error(f"Failed to set PixelFormat. This may cause further issues.")
            time.sleep(0.1)

            if not self._set(PROP_WIDTH, self.desired_width):
                log.error(f"Failed to set Width. This may cause further issues.")
            time.sleep(0.1)

            if not self._set(PROP_HEIGHT, self.desired_height):
                log.error(f"Failed to set Height. This may cause further issues.")
            time.sleep(0.1)

            try:
                log.debug(f"Attempting to find property 'AcquisitionFrameRateEnable'")
                prop_fps_enable = self.pm.find("AcquisitionFrameRateEnable")
                if prop_fps_enable:
                    log.debug(
                        f"'AcquisitionFrameRateEnable' found. Available: {prop_fps_enable.is_available}, ReadOnly: {prop_fps_enable.is_readonly}"
                    )
                    if prop_fps_enable.is_available and not prop_fps_enable.is_readonly:
                        if isinstance(prop_fps_enable, ic4.PropEnumeration):
                            if (
                                prop_fps_enable.selected_entry
                                and prop_fps_enable.selected_entry.name != "On"
                            ):
                                self._set("AcquisitionFrameRateEnable", "On")
                        elif isinstance(prop_fps_enable, ic4.PropBoolean):
                            if not prop_fps_enable.value:
                                self._set("AcquisitionFrameRateEnable", True)
                        else:
                            log.warning(
                                f"'AcquisitionFrameRateEnable' is of unexpected type: {type(prop_fps_enable)}"
                            )
            except ic4.IC4Exception as e_fps_enable:
                if (
                    hasattr(e_fps_enable, "code")
                    and e_fps_enable.code == ic4.ErrorCode.GenICamFeatureNotFound
                ):
                    log.warning(
                        "'AcquisitionFrameRateEnable' property not found. Proceeding without setting it."
                    )
                else:
                    log.error(
                        f"IC4Exception while trying to access 'AcquisitionFrameRateEnable': {str(e_fps_enable)}"
                    )
            except Exception as e_generic_fps_enable:
                log.error(
                    f"Generic exception while trying to access 'AcquisitionFrameRateEnable': {str(e_generic_fps_enable)}"
                )

            if not self._set(PROP_ACQUISITION_FRAME_RATE, self.target_fps):
                log.error(f"Failed to set AcquisitionFrameRate.")
            time.sleep(0.1)

            log.info("Setting AcquisitionMode and TriggerMode last...")
            if not self._set(PROP_ACQUISITION_MODE, "Continuous"):
                log.error(f"Failed to set AcquisitionMode.")
            time.sleep(0.1)

            if not self._set(PROP_TRIGGER_MODE, "Off"):
                log.error(
                    f"Failed to set TriggerMode to Off. Acquisition may fail if camera expects triggers."
                )

            log.info("SDKCameraThread: Camera configuration attempt finished.")

            self.listener = DummySinkListener()
            self.sink = ic4.QueueSink(self.listener)
            self.sink.timeout = 500
            log.info("SDKCameraThread: QueueSink created.")

            log.info(
                "SDKCameraThread: Attempting stream_setup with ACQUISITION_START option..."
            )
            self.camera_configured.emit(self.device, self.sink)
            return  # Exit the thread now that setup is done

            log.info("SDKCameraThread: Stream setup and acquisition possibly started.")

            frame_count = 0
            start_time = time.time()

            while not self._stop:
                try:
                    buf = self.sink.pop_output_buffer()

                    if buf is None:
                        log.debug(
                            "pop_output_buffer timed out (expected behavior if no frame ready)"
                        )
                        time.sleep(0.005)
                        continue

                    frame_count += 1
                    if frame_count % 100 == 0:
                        elapsed_time = time.time() - start_time
                        current_fps = (
                            frame_count / elapsed_time if elapsed_time > 0 else 0
                        )
                        log.debug(
                            f"Grabbed 100 frames. Total: {frame_count}. Current ingest FPS: {current_fps:.2f}"
                        )

                    w, h = buf.image_type.width, buf.image_type.height
                    pf_name = buf.image_type.pixel_format.name

                    qimage_format = None
                    if "Mono8" == pf_name:
                        qimage_format = QImage.Format_Grayscale8
                    elif pf_name in ("BGR8", "BGR8Packed"):
                        qimage_format = QImage.Format_RGB888
                    elif pf_name in ("RGB8", "RGB8Packed"):
                        qimage_format = QImage.Format_RGB888

                    if qimage_format is None:
                        log.warning(
                            f"Unsupported pixel format for QImage conversion: {pf_name}. Skipping frame."
                        )
                        continue

                    image_data = None
                    stride = 0
                    if hasattr(buf, "numpy_wrap"):
                        arr = buf.numpy_wrap()
                        image_data = arr.tobytes()
                        stride = (
                            arr.strides[0]
                            if len(arr.strides) > 0
                            else w * buf.image_type.bytes_per_pixel
                        )
                    else:
                        bytes_per_pixel = buf.image_type.bytes_per_pixel
                        pitch = getattr(buf, "pitch", w * bytes_per_pixel)
                        stride = pitch
                        buffer_size = pitch * h
                        image_data = ctypes.string_at(buf.pointer, buffer_size)

                    img = QImage(image_data, w, h, stride, qimage_format)

                    if (
                        pf_name in ("BGR8", "BGR8Packed")
                        and qimage_format == QImage.Format_RGB888
                    ):
                        pass

                    if not img.isNull():
                        self.frame_ready.emit(img.copy(), image_data)
                    else:
                        log.warning(
                            f"Failed to create QImage from buffer. w={w},h={h},pf={pf_name}"
                        )

                except ic4.IC4Exception as e:
                    if hasattr(e, "code") and e.code == ic4.ErrorCode.Timeout:
                        log.debug(
                            "pop_output_buffer IC4Exception Timeout (expected if no frame)"
                        )
                        time.sleep(0.005)
                        continue
                    log.error(
                        f"Acquisition loop IC4Exception: {str(e)} (Code: {e.code if hasattr(e, 'code') else 'N/A'})"
                    )
                    time.sleep(0.01)
                except Exception as e_loop:
                    log.exception(f"Unexpected error in acquisition loop: {e_loop}")
                    self._stop = True

        except ic4.IC4Exception as e:
            error_message = str(e)
            log.error(
                f"Camera thread setup IC4Exception: {error_message} (Code: {e.code if hasattr(e, 'code') else 'N/A'})"
            )
            self.camera_error.emit(f"{error_message}", "IC4Exception")
        except RuntimeError as e:
            log.error(f"Camera thread setup RuntimeError: {str(e)}")
            self.camera_error.emit(str(e), "RuntimeError")
        except Exception as e:
            log.exception("Camera thread setup generic error")
            self.camera_error.emit(str(e), type(e).__name__)
        finally:
            log.info(
                f"SDKCameraThread: Entering finally block. is_streaming: {self.grabber.is_streaming if self.grabber else 'N/A'}"
            )
            if self.grabber:
                try:
                    if self.grabber.is_streaming:
                        log.info(
                            "SDKCameraThread: Stopping stream (if it was considered started by the grabber)..."
                        )
                        # moved to main thread
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
