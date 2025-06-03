# File: prim_app/threads/sdk_camera_thread.py

import logging
import imagingcontrol4 as ic4
import numpy as np

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    """
    Opens the camera (using the DeviceInfo + resolution passed in via set_* methods),
    then immediately starts a QueueSink-based stream. Each new frame is emitted as a
    QImage via frame_ready(QImage, buffer). When stop() is called, it stops the stream
    and closes the camera.
    """

    # Emitted once the grabber is open (but before streaming starts).
    grabber_ready = pyqtSignal()

    # Emitted for each new frame: (QImage, raw_buffer_object)
    frame_ready = pyqtSignal(QImage, object)

    # Emitted on error: (message, code_as_string)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grabber = None
        self._stop_requested = False

        # Will be set by MainWindow before start():
        self._device_info = None  # an ic4.DeviceInfo instance
        self._resolution = None  # tuple (width, height, pixel_format_name)

        # We’ll keep a reference to the sink so we can cleanly stop it
        self._sink = None

    def set_device_info(self, dev_info):
        self._device_info = dev_info

    def set_resolution(self, resolution_tuple):
        # resolution_tuple is (w, h, pf_name), e.g. (2448, 2048, "Mono8")
        self._resolution = resolution_tuple

    def run(self):
        try:
            # -----------------------------------------------------------------
            # 1) Initialize IC4 in this thread (if not already done globally)
            # -----------------------------------------------------------------
            try:
                ic4.Library.init(
                    api_log_level=ic4.LogLevel.INFO,
                    log_targets=ic4.LogTarget.STDERR,
                )
                log.info("SDKCameraThread: Library.init() succeeded.")
            except RuntimeError as e:
                # If “Library.init was already called,” ignore and continue
                if "already called" in str(e):
                    log.info("SDKCameraThread: IC4 already initialized; continuing.")
                else:
                    raise

            # -----------------------------------------------------------------
            # 2) Verify we have a DeviceInfo
            # -----------------------------------------------------------------
            if self._device_info is None:
                raise RuntimeError("No DeviceInfo passed to SDKCameraThread.")

            # -----------------------------------------------------------------
            # 3) Open the grabber
            # -----------------------------------------------------------------
            self.grabber = ic4.Grabber()
            self.grabber.device_open(self._device_info)
            log.info(
                f"SDKCameraThread: device_open() succeeded for "
                f"'{self._device_info.model_name}' (S/N '{self._device_info.serial}')."
            )

            # -----------------------------------------------------------------
            # 4) Apply resolution + PixelFormat if provided
            # -----------------------------------------------------------------
            if self._resolution is not None:
                w, h, pf_name = self._resolution
                try:
                    pf_node = self.grabber.device_property_map.find_enumeration(
                        "PixelFormat"
                    )
                    if pf_node:
                        pf_node.value = pf_name
                        log.info(f"SDKCameraThread: Set PixelFormat = {pf_name}")
                        w_node = self.grabber.device_property_map.find_integer("Width")
                        h_node = self.grabber.device_property_map.find_integer("Height")
                        if w_node and h_node:
                            w_node.value = w
                            h_node.value = h
                            log.info(f"SDKCameraThread: Set resolution = {w}×{h}")
                    else:
                        log.warning(
                            "SDKCameraThread: PixelFormat node not found; using camera default."
                        )
                except Exception as e:
                    log.warning(f"SDKCameraThread: Could not set resolution/PF: {e}")

            # -----------------------------------------------------------------
            # 5) Signal “grabber_ready” so MainWindow can build controls, etc.
            # -----------------------------------------------------------------
            self.grabber_ready.emit()

            # -----------------------------------------------------------------
            # 6) Build a QueueSink requesting Mono8 frames (max_output_buffers=1).
            #    We assume resolution’s pf_name is “Mono8.” If it were Mono10 or Mono16,
            #    IC4 might automatically downconvert, else we’d receive 16-bit buffers
            #    which we then scale below.
            # -----------------------------------------------------------------
            try:
                # Request exactly Mono8 from the camera
                self._sink = ic4.QueueSink(
                    self, [ic4.PixelFormat.Mono8], max_output_buffers=1
                )
            except Exception:
                # Fallback: if camera can only deliver its native pf_name,
                # request that instead (pf_name might be "Mono8" anyway).
                native_pf = self._resolution[2] if self._resolution else None
                if native_pf and hasattr(ic4.PixelFormat, native_pf):
                    self._sink = ic4.QueueSink(
                        self, [ic4.PixelFormat[native_pf]], max_output_buffers=1
                    )
                else:
                    raise RuntimeError(
                        "SDKCameraThread: Unable to create a QueueSink for Mono8 or native PF."
                    )

            self.grabber.stream_setup(self._sink)
            log.info("SDKCameraThread: stream_setup() succeeded.")

            # -----------------------------------------------------------------
            # 7) Start streaming. After this, frames_queued() will be called for each frame.
            # -----------------------------------------------------------------
            self.grabber.stream_start()
            log.info(
                "SDKCameraThread: stream_start() succeeded. Entering frame loop..."
            )

            # -----------------------------------------------------------------
            # 8) Busy‐loop until stop() is called. frames_queued() will handle incoming images.
            # -----------------------------------------------------------------
            while not self._stop_requested:
                ic4.sleep(10)  # ~10 ms sleep

            # -----------------------------------------------------------------
            # 9) On stop request: stop streaming, close device
            # -----------------------------------------------------------------
            self.grabber.stream_stop()
            self.grabber.device_close()
            log.info("SDKCameraThread: Streaming stopped, device closed.")

        except Exception as e:
            # Emit any errors
            msg = str(e)
            code_enum = getattr(e, "code", None)
            code_str = str(code_enum) if code_enum else ""
            log.exception("SDKCameraThread: encountered an error.")
            self.error.emit(msg, code_str)

        finally:
            # -----------------------------------------------------------------
            # 10) Exit IC4 for this thread (decrements internal reference count)
            # -----------------------------------------------------------------
            try:
                ic4.Library.exit()
                log.info("SDKCameraThread: Library.exit() called.")
            except Exception:
                pass

    def frames_queued(self, sink):
        """
        This callback is invoked by IC4 each time a new buffer is available.
        We pop the buffer, convert its data (Mono8 or Mono16) to a QImage, emit it,
        then let IC4 recycle the buffer automatically.
        """
        try:
            buf = sink.pop_output_buffer()
            arr = (
                buf.numpy_wrap()
            )  # arr: shape=(H, W) with dtype=uint8 (Mono8) or uint16

            # If dtype is 8-bit, we can use it directly. If 16-bit, scale to 8-bit.
            if arr.dtype == np.uint8:
                gray8 = arr
            else:
                # Convert 10/16‐bit → 8‐bit by linear scaling
                max_val = float(arr.max()) if arr.max() > 0 else 1.0
                scale = 255.0 / max_val
                gray8 = (arr.astype(np.float32) * scale).astype(np.uint8)

            h, w = gray8.shape[:2]

            # Create a QImage from single‐channel grayscale
            qimg = QImage(gray8.data, w, h, gray8.strides[0], QImage.Format_Grayscale8)

            # Emit the frame
            self.frame_ready.emit(qimg, buf)

        except Exception as e:
            log.error(
                f"SDKCameraThread.frames_queued: Error popping/converting buffer: {e}"
            )
            code_enum = getattr(e, "code", None)
            code_str = str(code_enum) if code_enum else ""
            self.error.emit(str(e), code_str)

    def stop(self):
        """
        Request the streaming loop to end. After this returns, run() will clean up.
        """
        self._stop_requested = True
