# prim_app/threads/sdk_camera_thread.py

import logging
import imagingcontrol4 as ic4
import numpy as np

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    """
    Opens the camera (using the DeviceInfo + resolution passed in via set_* methods),
    then starts a QueueSink-based stream. Each new frame is emitted as a QImage via
    frame_ready(QImage, buffer). When stop() is called, stops streaming and closes the device.
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

        # Keep a reference to the sink so we can stop it later
        self._sink = None

    def set_device_info(self, dev_info):
        self._device_info = dev_info

    def set_resolution(self, resolution_tuple):
        # resolution_tuple is (w, h, pf_name), e.g. (2448, 2048, "Mono8")
        self._resolution = resolution_tuple

    def run(self):
        """
        Main thread entry.  Does exactly what was working before:
          1) Initialize IC4
          2) Open self._device_info
          3) Apply self._resolution (if provided)
          4) Force AcquisitionMode = Continuous
          5) Create a Mono8 QueueSink → start streaming
          6) Emit grabber_ready()
          7) Loop (sleep) until stop() is called
        """
        try:
            # ─── 1) Initialize the IC4 library (once per process) ──────────────
            try:
                ic4.Library.init(
                    api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR
                )
                log.info("SDKCameraThread: Library.init() succeeded.")
            except RuntimeError:
                # Already initialized; ignore.
                pass

            # ─── 2) Ensure MainWindow gave us a DeviceInfo ────────────────────
            if self._device_info is None:
                raise RuntimeError("No DeviceInfo passed to SDKCameraThread.")

            # ─── 3) Open the Grabber ──────────────────────────────────────────
            self.grabber = ic4.Grabber()
            self.grabber.device_open(self._device_info)
            log.info(
                f"SDKCameraThread: device_open() succeeded for "
                f"'{self._device_info.model_name}' (S/N '{self._device_info.serial}')."
            )

            # ─── 4) If resolution was provided, apply it (PF, Width, Height) ─
            if self._resolution:
                w, h, pf_name = self._resolution
                try:
                    # Set PixelFormat first:
                    pf_node = self.grabber.device_property_map.find_enumeration(
                        "PixelFormat"
                    )
                    if pf_node and pf_name in [entry.name for entry in pf_node.entries]:
                        pf_node.value = pf_name
                        # Then set Width and Height:
                        w_node = self.grabber.device_property_map.find_integer("Width")
                        h_node = self.grabber.device_property_map.find_integer("Height")
                        if w_node and h_node:
                            w_node.value = w
                            h_node.value = h
                            log.info(
                                f"SDKCameraThread: Set resolution = {w}×{h} ({pf_name})"
                            )
                        else:
                            log.warning(
                                "SDKCameraThread: Could not find Width/Height nodes."
                            )
                    else:
                        log.warning(
                            "SDKCameraThread: PixelFormat node not found or invalid."
                        )
                except Exception as e:
                    log.warning(f"SDKCameraThread: Could not set resolution/PF: {e}")

            # ─── 5) Force AcquisitionMode = Continuous ────────────────────────
            try:
                acq_node = self.grabber.device_property_map.find_enumeration(
                    "AcquisitionMode"
                )
                if acq_node:
                    names = [entry.name for entry in acq_node.entries]
                    if "Continuous" in names:
                        acq_node.value = "Continuous"
                        log.info("SDKCameraThread: Set AcquisitionMode = Continuous")
                    else:
                        acq_node.value = names[0]
                        log.info(f"SDKCameraThread: Set AcquisitionMode = {names[0]}")
            except Exception as e:
                log.warning(f"SDKCameraThread: Could not set AcquisitionMode: {e}")

            # ─── 6) Disable any trigger (so camera is free-running) ─────────
            try:
                trig_sel = self.grabber.device_property_map.find_enumeration(
                    "TriggerSelector"
                )
                if trig_sel and "FrameStart" in [
                    entry.name for entry in trig_sel.entries
                ]:
                    trig_sel.value = "FrameStart"
                trig_mode = self.grabber.device_property_map.find_enumeration(
                    "TriggerMode"
                )
                if trig_mode and "Off" in [entry.name for entry in trig_mode.entries]:
                    trig_mode.value = "Off"
            except Exception:
                pass

            # ─── 7) Signal “grabber_ready” so the UI can enable controls ─────
            self.grabber_ready.emit()

            # ─── 8) Build a Mono8 QueueSink ──────────────────────────────────
            try:
                self._sink = ic4.QueueSink(
                    self, [ic4.PixelFormat.Mono8], max_output_buffers=1
                )
            except Exception:
                # If Mono8 isn’t available, fall back to native PF if possible
                native_pf = self._resolution[2] if self._resolution else None
                if native_pf and hasattr(ic4.PixelFormat, native_pf):
                    self._sink = ic4.QueueSink(
                        self,
                        [getattr(ic4.PixelFormat, native_pf)],
                        max_output_buffers=1,
                    )
                else:
                    raise RuntimeError(
                        "SDKCameraThread: Unable to create QueueSink for Mono8 or native PF."
                    )

            # ─── 9) Start continuous streaming immediately ─────────────────────
            from imagingcontrol4 import StreamSetupOption

            self.grabber.stream_setup(
                self._sink,
                setup_option=StreamSetupOption.ACQUISITION_START,
            )
            log.info(
                "SDKCameraThread: stream_setup(ACQUISITION_START) succeeded. Entering frame loop…"
            )

            # ─── 10) Hook sink callback ───────────────────────────────────────
            self._sink.signal_frame_ready.connect(self.frames_queued)

            # ─── 11) Enter a small‐sleep loop until stop() is called ─────────
            self._stop_requested = False
            while not self._stop_requested:
                self.msleep(10)

            # ─── 12) Stop streaming & close device ───────────────────────────
            self.grabber.stream_stop()
            self.grabber.device_close()

        except Exception as ex:
            log.critical(f"SDKCameraThread: Exception in run(): {ex}")
            self.error.emit(str(ex), "RunError")
        finally:
            # Cleanup if still streaming
            try:
                if self._sink is not None:
                    self._sink.signal_frame_ready.disconnect(self.frames_queued)
                    self.grabber.stream_stop()
                    self._sink.close()
                    self._sink = None
            except Exception as e:
                log.error(f"SDKCameraThread: Error stopping continuous mode: {e}")

            try:
                ic4.Library.exit()
            except Exception:
                pass
            log.info("SDKCameraThread: Thread exiting (cleaned up).")

    # ─── Required listener methods for QueueSink ─────────────────────────────
    def sink_connected(self, sink, pixel_format, min_buffers_required) -> bool:
        # Return True so the sink actually attaches
        return True

    def sink_disconnected(self, sink) -> None:
        # Called when the sink is torn down—no action needed
        pass

    def stop(self):
        """
        Request the streaming loop to end.  This will cause run() to clean up and exit.
        """
        self._stop_requested = True

    def frames_queued(self, sink):
        """
        Pop the buffer, convert to QImage, emit frame_ready, and recycle the buffer.
        (This is exactly what was working for live preview.)
        """
        try:
            buf = sink.pop_output_buffer()
            arr = buf.numpy_wrap()  # arr: 2D array, dtype uint8 or uint16

            # Downconvert 16-bit → 8-bit if needed:
            if arr.dtype == np.uint8:
                gray8 = arr
            else:
                max_val = float(arr.max()) if arr.max() > 0 else 1.0
                scale = 255.0 / max_val
                gray8 = (arr.astype(np.float32) * scale).astype(np.uint8)

            h, w = gray8.shape[:2]
            qimg = QImage(gray8.data, w, h, gray8.strides[0], QImage.Format_Grayscale8)
            qimg_copy = qimg.copy()
            self.frame_ready.emit(qimg_copy, buf)

            buf.queue()  # Return the buffer to IC4

        except Exception as e:
            log.error(
                f"SDKCameraThread.frames_queued: Error popping/converting buffer: {e}"
            )
            try:
                buf.queue()
            except Exception:
                log.error(
                    f"SDKCameraThread.frames_queued: could not re-queue buffer: {e}"
                )
