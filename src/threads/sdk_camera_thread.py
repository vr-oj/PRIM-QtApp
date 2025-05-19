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
    Listener for queue sink: allocates buffers on connection.
    """

    def sink_connected(self, sink, image_type, min_buffers_required):
        log.debug(
            f"Sink connected: {image_type}, buffers needed: {min_buffers_required}"
        )
        sink.alloc_and_queue_buffers(min_buffers_required)
        return True

    def sink_disconnected(self, sink):
        log.debug(f"Sink disconnected: {type(sink)}")


class SDKCameraThread(QThread):
    """
    Thread managing camera acquisition via the IC4 SDK.

    Emits:
        frame_ready (QImage, mem_ptr)
        camera_resolutions_available (list)
        camera_properties_updated (dict)
        camera_error (message, code)
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

        self.grabber = None
        self.sink = None
        self.pm = None
        self.actual_qimage_format = QImage.Format_Grayscale8

    def run(self):
        try:
            # Open the camera device
            self.grabber = ic4.Grabber()
            self.grabber.device_open(self.device_info)
            log.info(f"Device opened: {self.device_info.model_name}")
            self.pm = self.grabber.device_property_map

            # === Configure camera properties ===
            # 1) Pixel format (optional)
            pf_prop = self.pm.find(PROP_PIXEL_FORMAT)
            if pf_prop and pf_prop.is_available:
                try:
                    pf_prop.value = PropEnumEntry(
                        self.pm, PROP_PIXEL_FORMAT, self.desired_pixel_format_str
                    )
                    log.info(f"Pixel format set to {self.desired_pixel_format_str}")
                except Exception as e:
                    log.warning(
                        f"Could not set pixel format '{self.desired_pixel_format_str}': {e}; using default '{pf_prop.value}'"
                    )
            else:
                log.warning(f"'{PROP_PIXEL_FORMAT}' not available or not supported.")

            # 2) Region of interest: width & height
            w_prop = self.pm.find(PROP_WIDTH)
            h_prop = self.pm.find(PROP_HEIGHT)
            if w_prop and h_prop and w_prop.is_available and h_prop.is_available:
                w_prop.value = int(self.desired_width)
                h_prop.value = int(self.desired_height)
                log.info(f"ROI set to {self.desired_width}x{self.desired_height}")

            # 3) Acquisition mode, trigger mode, frame rate
            acq_mode = self.pm.find(PROP_ACQUISITION_MODE)
            trg_mode = self.pm.find(PROP_TRIGGER_MODE)
            fr_prop = self.pm.find(PROP_ACQUISITION_FRAME_RATE)
            if acq_mode and acq_mode.is_available:
                acq_mode.value = PropEnumEntry(
                    self.pm, PROP_ACQUISITION_MODE, "Continuous"
                )
            if trg_mode and trg_mode.is_available:
                trg_mode.value = PropEnumEntry(self.pm, PROP_TRIGGER_MODE, "Off")
            if fr_prop and fr_prop.is_available:
                fr_prop.value = float(self.target_fps)
                log.info(f"Frame rate set to {self.target_fps} FPS")

            # === Setup streaming ===
            listener = DummySinkListener()
            self.sink = ic4.QueueSink(listener)
            log.info("QueueSink created")

            # Small delay before start
            time.sleep(0.1)
            self.grabber.stream_setup(
                self.sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            log.info("Stream setup complete; acquisition starting")

            # === Frame acquisition loop ===
            last_time = time.monotonic()
            counter = 0
            log.info("Entering acquisition loop")
            while not self._stop_requested:
                try:
                    buf = self.sink.pop_output_buffer()
                except ic4.IC4Exception as e:
                    # Ignore timeouts
                    continue

                if buf is None:
                    continue

                counter += 1
                log.debug(
                    f"Frame {counter} received: {buf.image_type.width}x{buf.image_type.height} {buf.image_type.pixel_format.name}"
                )

                # Convert to QImage
                qimg = QImage(
                    buf.mem_ptr,
                    buf.image_type.width,
                    buf.image_type.height,
                    buf.image_type.stride_bytes,
                    self.actual_qimage_format,
                )
                if not qimg.isNull():
                    self.frame_ready.emit(qimg.copy(), buf.mem_ptr)
                else:
                    log.error("Failed to create QImage from buffer")

                # Pace to target FPS
                now = time.monotonic()
                elapsed = now - last_time
                interval = 1.0 / self.target_fps
                if elapsed < interval:
                    self.msleep(int((interval - elapsed) * 1000))
                last_time = time.monotonic()

            log.info("Acquisition loop exited")

        except Exception as e:
            log.exception("Unhandled exception in SDKCameraThread.run()")
            self.camera_error.emit(str(e), type(e).__name__)

        finally:
            # Cleanup
            try:
                self.grabber.stream_stop()
                log.info("Stream stopped")
            except Exception:
                pass
            try:
                self.grabber.device_close()
                log.info("Device closed")
            except Exception:
                pass
            log.info(
                f"SDKCameraThread for {getattr(self.device_info, 'model_name', 'device')} stopped"
            )
