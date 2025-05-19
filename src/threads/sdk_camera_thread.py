import logging
import time
import imagingcontrol4 as ic4

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

from imagingcontrol4.properties import (
    PropInteger,
    PropFloat,
    PropBoolean,
    PropEnumeration,
    PropEnumEntry,
)

# Property names for configuring the camera
PROP_WIDTH = "Width"
PROP_HEIGHT = "Height"
PROP_PIXEL_FORMAT = "PixelFormat"
PROP_EXPOSURE = "ExposureTime"
PROP_GAIN = "Gain"
PROP_ACQUISITION_MODE = "AcquisitionMode"
PROP_TRIGGER_MODE = "TriggerMode"
PROP_ACQUISITION_FRAME_RATE = "AcquisitionFrameRate"

log = logging.getLogger(__name__)


class DummySinkListener:
    """
    A simple listener for the queue sink. Allocates buffers when the sink is connected.
    """

    def sink_connected(self, sink, image_type, min_buffers_required):
        log.debug(
            f"DummyListener: Sink connected. ImageType: {image_type}, MinBuffers: {min_buffers_required}"
        )
        # Allocate required buffers for the sink
        sink.alloc_and_queue_buffers(min_buffers_required)
        return True

    def frames_queued(self, sink, userdata):
        # Not used; we poll directly in the thread
        pass

    def sink_disconnected(self, sink):
        log.debug(f"DummyListener: Sink disconnected (event for sink: {type(sink)}).")
        pass


class SDKCameraThread(QThread):
    """
    Thread managing the camera acquisition via the IC4 SDK.

    Emits:
        frame_ready (QImage, mem_ptr) when a new frame is captured.
        camera_resolutions_available (list) when supported resolutions change.
        camera_properties_updated (dict) when camera controls update.
        camera_error (str, str) on error, with message and exception type.
    """

    frame_ready = pyqtSignal(QImage, object)
    camera_resolutions_available = pyqtSignal(list)
    camera_properties_updated = pyqtSignal(dict)
    camera_error = pyqtSignal(str, str)

    def __init__(
        self,
        device_info,
        target_fps=20.0,
        desired_width=640,
        desired_height=480,
        desired_pixel_format="Mono8",
        parent=None,
    ):
        super().__init__(parent)
        self._stop_requested = False
        self.device_info = device_info
        self.target_fps = target_fps
        self.desired_width = desired_width
        self.desired_height = desired_height
        self.desired_pixel_format_str = desired_pixel_format

        self._pending_exposure_us = None
        self._pending_gain_db = None
        self._pending_auto_exposure = None
        self._pending_roi = None

        self.grabber = None
        self.sink = None
        self.pm = None
        self.actual_qimage_format = QImage.Format_Grayscale8

    def run(self):
        try:
            # Initialize grabber and open device
            self.grabber = ic4.Grabber()
            self.grabber.system_open()
            self.grabber.device_open(self.device_info)
            log.info(f"Device opened: {self.device_info.model_name}")
            self.pm = self.grabber.device_property_map

            # Configure critical properties BEFORE stream_setup
            try:
                # Set pixel format to Mono8 or equivalent
                current_pf_prop = self.pm.find(PROP_PIXEL_FORMAT)
                if not (current_pf_prop and current_pf_prop.is_available):
                    raise RuntimeError(f"'{PROP_PIXEL_FORMAT}' not available.")
                current_pf_val = current_pf_prop.value
                if current_pf_val.replace(" ", "").lower() != "mono8":
                    self._set_property_value(
                        PROP_PIXEL_FORMAT, self.desired_pixel_format_str
                    )
                # Set width, height, acquisition mode, trigger, fps similarly...
                # Apply pending properties
            except Exception as e:
                log.error(f"Critical property setup error: {e}", exc_info=True)
                self.camera_error.emit(f"Camera Config Error: {e}", type(e).__name__)
                return

            # Create and configure queue sink listener
            self.dummy_listener = DummySinkListener()
            self.sink = ic4.QueueSink(self.dummy_listener)
            if hasattr(self.sink, "accept_incomplete_frames"):
                try:
                    self.sink.accept_incomplete_frames = False
                except Exception as e:
                    log.warning(f"Could not set accept_incomplete_frames: {e}")
            log.info("QueueSink created.")

            # Brief pause before starting acquisition
            time.sleep(0.2)
            self.grabber.stream_setup(
                self.sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            log.info("Stream setup complete; acquisition starting.")

            # Enter acquisition loop
            log.info("Entering frame acquisition loop...")
            frame_counter = 0
            null_buffer_counter = 0
            last_frame_time = time.monotonic()

            while not self._stop_requested:
                self._apply_pending_properties()
                buf = None
                try:
                    # Retrieve the next available image buffer (blocking)
                    buf = self.sink.pop_output_buffer()
                except ic4.IC4Exception as e:
                    # Handle stream timeout or other errors
                    if hasattr(e, "code") and e.code == ic4.ErrorCode.TIMEOUT:
                        null_buffer_counter += 1
                        continue
                    log.error(
                        f"IC4Exception during sink.pop_output_buffer: {e}",
                        exc_info=True,
                    )
                    self.camera_error.emit(
                        str(e), f"SinkPop ({e.code if hasattr(e,'code') else 'N/A'})"
                    )
                    break

                if buf is None:
                    null_buffer_counter += 1
                    continue

                frame_counter += 1
                log.debug(
                    f"Frame {frame_counter}: Buffer received. Resolution: {buf.image_type.width}x{buf.image_type.height}, Format: {buf.image_type.pixel_format.name}"
                )
                null_buffer_counter = 0

                try:
                    # Wrap raw memory into QImage for display
                    qimg = QImage(
                        buf.mem_ptr,
                        buf.image_type.width,
                        buf.image_type.height,
                        buf.image_type.stride_bytes,
                        self.actual_qimage_format,
                    )
                    if qimg.isNull():
                        log.error(f"Frame {frame_counter}: QImage creation failed.")
                    else:
                        self.frame_ready.emit(qimg.copy(), buf.mem_ptr)
                finally:
                    pass

                # Throttle to target FPS
                now = time.monotonic()
                dt = now - last_frame_time
                target_interval = 1.0 / self.target_fps if self.target_fps > 0 else 0.05
                if dt < target_interval:
                    sleep_ms = int((target_interval - dt) * 1000)
                    if sleep_ms > 5:
                        self.msleep(sleep_ms)
                last_frame_time = time.monotonic()

            log.info("Exited frame acquisition loop.")
        except Exception as e:
            log.exception("Unhandled exception in SDKCameraThread.run():")
            self.camera_error.emit(str(e), type(e).__name__)
        finally:
            # Clean up streaming and device
            if self.grabber:
                try:
                    if getattr(self.grabber, "is_streaming", False):
                        self.grabber.stream_stop()
                        log.info("Stream stopped.")
                except Exception:
                    pass
                try:
                    if getattr(self.grabber, "is_device_open", False):
                        self.grabber.device_close()
                        log.info("Device closed.")
                except Exception as e:
                    log.error(f"Error closing device: {e}")
            log.info(
                f"SDKCameraThread ({self.device_info.model_name if self.device_info else 'N/A'}) fully stopped."
            )
            self.grabber, self.sink, self.pm = None, None, None
