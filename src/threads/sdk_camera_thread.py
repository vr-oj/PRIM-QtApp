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
    Listener for the queue sink: allocates buffers on connection.
    """

    def sink_connected(self, sink, image_type, min_buffers_required):
        log.debug(
            f"Sink connected: {image_type}, buffers required: {min_buffers_required}"
        )
        sink.alloc_and_queue_buffers(min_buffers_required)
        return True

    def sink_disconnected(self, sink):
        log.debug(f"Sink disconnected: {type(sink)}")


class SDKCameraThread(QThread):
    """
    Thread managing camera acquisition via IC4 SDK.

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

        # Placeholder for property updates
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
            # Initialize grabber and open the selected device
            self.grabber = ic4.Grabber()
            self.grabber.device_open(self.device_info)
            log.info(f"Device opened: {self.device_info.model_name}")
            self.pm = self.grabber.device_property_map

            # Configure critical properties before starting stream
            try:
                # Set pixel format
                pf_prop = self.pm.find(PROP_PIXEL_FORMAT)
                if not (pf_prop and pf_prop.is_available):
                    raise RuntimeError(f"'{PROP_PIXEL_FORMAT}' not available")
                if pf_prop.value != self.desired_pixel_format_str:
                    pf_prop.value = self.desired_pixel_format_str

                # Set ROI: width & height
                w_prop = self.pm.find(PROP_WIDTH)
                h_prop = self.pm.find(PROP_HEIGHT)
                if w_prop and h_prop and w_prop.is_available and h_prop.is_available:
                    w_prop.value = self.desired_width
                    h_prop.value = self.desired_height

                # Set acquisition mode, trigger mode, and frame rate
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

            except Exception as e:
                log.error("Camera configuration failed", exc_info=True)
                self.camera_error.emit(f"Config Error: {e}", type(e).__name__)
                return

            # Create sink and listener
            listener = DummySinkListener()
            self.sink = ic4.QueueSink(listener)
            log.info("QueueSink created")

            # Start acquisition
            time.sleep(0.2)
            self.grabber.stream_setup(
                self.sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            log.info("Stream setup and acquisition started")

            # Acquisition loop
            log.info("Entering acquisition loop")
            last_frame_time = time.monotonic()
            frame_count = 0
            while not self._stop_requested:
                try:
                    buf = self.sink.pop_output_buffer()
                except ic4.IC4Exception as e:
                    log.warning(f"Sink timeout/error: {e}")
                    continue

                if buf is None:
                    continue

                frame_count += 1
                log.debug(f"Frame {frame_count} received")

                try:
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
                        log.error("QImage creation returned null image")
                finally:
                    pass

                # Enforce target FPS
                now = time.monotonic()
                dt = now - last_frame_time
                interval = 1.0 / self.target_fps
                if dt < interval:
                    self.msleep(int((interval - dt) * 1000))
                last_frame_time = time.monotonic()

            log.info("Acquisition loop exited")

        except Exception as e:
            log.exception("Unhandled exception in SDKCameraThread.run()")
            self.camera_error.emit(str(e), type(e).__name__)

        finally:
            # Cleanup: stop stream and close device
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
            log.info(f"SDKCameraThread for {self.device_info.model_name} stopped")
            self.grabber = None
            self.sink = None
            self.pm = None
