import sys
import logging
import threading
from PyQt5.QtCore import QThread, pyqtSignal
import ic4

logger = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    """
    QThread subclass that opens a camera via IC Imaging Control 4, configures it,
    and continually grabs frames from a QueueSink. Each new frame is emitted
    via a PyQt signal as a raw numpy array.

    Emits:
        new_frame(array, width, height): whenever a new frame arrives
        error(str): if any camera error occurs
    """

    # Emitted whenever we have a new frame ready. The frame is passed as a raw
    # byte-array (numpy-compatible), along with width and height.
    new_frame = pyqtSignal(object, int, int)

    # Emitted if any error occurs inside the thread.
    error = pyqtSignal(str)

    def __init__(
        self,
        camera_serial: str,
        pixel_format: str = "Mono8",
        width: int = 2448,
        height: int = 2048,
        parent=None,
    ):
        """
        Args:
            camera_serial: the serial number (S/N) of the camera to open
            pixel_format: one of the camera’s supported pixel-format names
            width, height: desired acquisition resolution
            parent: standard QObject parent for the QThread
        """
        super().__init__(parent)
        self._camera_serial = camera_serial
        self._pixel_format = pixel_format
        self._target_width = width
        self._target_height = height

        self._stop_requested = False

        # We’ll store references here so that Python doesn’t collect them prematurely:
        self._grabber = None  # ic4.Grabber
        self._sink = None  # ic4.QueueSink

    def stop(self):
        """
        Signals the thread to stop. Once this is called, the next time the loop in run()
        checks, it will break and shut down cleanly.
        """
        self._stop_requested = True

    def run(self):
        """
        Main thread entry point. Initializes IC4 (only on the first camera open),
        opens the camera, configures it, creates a QueueSink, starts streaming, and
        enters a loop that pops buffers from the sink, emits them, and then lets them
        be recycled automatically.
        """
        try:
            # Initialize IC4 (if not already initialized).
            if not ic4.Library.is_initialized():
                ic4.Library.init()
                logger.info("SDKCameraThread: IC4 Library initialized.")
            else:
                logger.info("SDKCameraThread: IC4 already initialized; continuing.")

            # Create a Grabber, open the device by serial number:
            self._grabber = ic4.Grabber()
            self._grabber.device_open(serial=self._camera_serial)
            logger.info(
                f"SDKCameraThread: device_open() succeeded for S/N '{self._camera_serial}'."
            )

            # Set PixelFormat, Resolution, AcquisitionMode, and TriggerMode:
            # (If any of these fail, IC4 will throw an exception.)
            node_map = self._grabber.device_node_map()

            # PixelFormat
            node_map["PixelFormat".encode("utf-8")].value = self._pixel_format
            logger.info(f"SDKCameraThread: Set PixelFormat = '{self._pixel_format}'")

            # Width & Height
            node_map["Width".encode("utf-8")].value = self._target_width
            node_map["Height".encode("utf-8")].value = self._target_height
            logger.info(
                f"SDKCameraThread: Set resolution = {self._target_width}×{self._target_height}"
            )

            # AcquisitionMode → Continuous
            node_map["AcquisitionMode".encode("utf-8")].value = "Continuous"
            logger.info("SDKCameraThread: Set AcquisitionMode = Continuous")

            # TriggerMode → Off
            node_map["TriggerMode".encode("utf-8")].value = "Off"
            logger.info("SDKCameraThread: Set TriggerMode = Off")

            # Create a QueueSink that will hold up to 8 output buffers for our chosen pixel format:
            pf_list = [self._pixel_format]
            max_buffers = 8
            self._sink = ic4.QueueSink(pf_list, max_output_buffers=max_buffers)
            logger.info(
                f"SDKCameraThread: Created QueueSink for PFs = {pf_list}, max_output_buffers={max_buffers}"
            )

            # Attach the sink to the grabber and start streaming:
            self._grabber.stream_put(self._sink)
            self._grabber.stream_setup(ic4.StreamCommand.ACQUISITION_START)
            logger.info(
                "SDKCameraThread: stream_setup(ACQUISITION_START) succeeded. Entering frame loop…"
            )

            # Frame‐popping loop:
            while not self._stop_requested:
                try:
                    # Wait up to 1000 ms for the next buffer. If none arrives, a timeout exception is raised.
                    buf = self._sink.pop_output_buffer(timeout_ms=1000)
                except ic4.IC4Exception as e:
                    # If it’s a timeout, just loop back and check _stop_requested again.
                    if e.error_code == ic4.ErrorCode.Timeout:
                        continue
                    else:
                        # Any other error must be reported and break out.
                        raise

                # We got a valid ImageBuffer → convert it to a numpy array:
                try:
                    img_bytes = buf.ptr_data()  # raw pointer to image bytes
                    size = buf.image_size()  # total number of bytes
                    width = buf.image_width()
                    height = buf.image_height()

                    # Copy out to Python bytes; after this, dropping 'buf' will automatically requeue it:
                    raw = img_bytes[:size]  # memcpy‐style; create a bytes object

                    # Emit the raw bytes plus dimensions
                    self.new_frame.emit(raw, width, height)
                finally:
                    # IMPORTANT: simply delete our reference to buf so that IC4 can recycle it:
                    del buf

            # If we ever exit the loop (stop requested), stop acquisition:
            self._grabber.stream_setup(ic4.StreamCommand.ACQUISITION_STOP)
            logger.info("SDKCameraThread: stream_setup(ACQUISITION_STOP) called.")

        except Exception as ex:
            # Catch any exceptions; emit an error signal, then clean up and exit.
            msg = f"{ex.__class__.__name__}: {ex}"
            logger.error(f"SDKCameraThread: UNHANDLED ERROR → {msg}")
            self.error.emit(msg)

            # If the grabber was open/streaming, try to stop it properly:
            try:
                if self._grabber is not None:
                    self._grabber.stream_setup(ic4.StreamCommand.ACQUISITION_STOP)
            except Exception:
                pass
        finally:
            # Ensure we close the device and release IC4 objects:
            try:
                if self._grabber is not None and self._grabber.device_is_open():
                    self._grabber.device_close()
                    logger.info("SDKCameraThread: device_close() succeeded.")
            except Exception:
                pass

            # Release references so Python can garbage‐collect IC4 objects:
            self._sink = None
            self._grabber = None
            logger.info("SDKCameraThread: Thread exiting cleanly.")
