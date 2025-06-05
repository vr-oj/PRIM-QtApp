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
        # We keep this around in case you want to read it,
        # but we will NOT attempt to apply it in run().
        self._resolution = resolution_tuple

    def run(self):
        try:
            # ─── Initialize IC4 (with “already called” catch) ─────────────────
            try:
                ic4.Library.init(
                    api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR
                )
                log.info("SDKCameraThread: Library.init() succeeded.")
            except RuntimeError as e:
                if "already called" in str(e):
                    log.info("SDKCameraThread: IC4 already initialized; continuing.")
                else:
                    raise

            # ─── Verify device_info was set ────────────────────────────────────
            if self._device_info is None:
                raise RuntimeError("No DeviceInfo passed to SDKCameraThread.")

            # ─── Open the grabber ───────────────────────────────────────────────
            self.grabber = ic4.Grabber()
            self.grabber.device_open(self._device_info)
            log.info(
                f"SDKCameraThread: device_open() succeeded for "
                f"'{self._device_info.model_name}' (S/N '{self._device_info.serial}')."
            )

            # ─── [REMOVED] Apply PixelFormat & resolution ──────────────────────
            # We are no longer forcing the camera into a specific PF or resolution here.
            # The grabber will remain in its factory default PixelFormat/Width/Height.

            # ─── 1) Force Continuous acquisition mode (so camera is in free‐run) ───
            try:
                acq_node = self.grabber.device_property_map.find_enumeration(
                    "AcquisitionMode"
                )
                if acq_node:
                    entries = [e.name for e in acq_node.entries]
                    if "Continuous" in entries:
                        acq_node.value = "Continuous"
                        log.info("SDKCameraThread: Set AcquisitionMode = Continuous")
                    else:
                        acq_node.value = entries[0]
                        log.info(f"SDKCameraThread: Set AcquisitionMode = {entries[0]}")
            except Exception as e:
                log.warning(f"SDKCameraThread: Could not set AcquisitionMode: {e}")

            # ─── 2) Disable TriggerMode (so it doesn’t wait for external trigger) ─
            try:
                trig_node = self.grabber.device_property_map.find_enumeration(
                    "TriggerMode"
                )
                if trig_node:
                    trig_node.value = "Off"
                    log.info("SDKCameraThread: Set TriggerMode = Off")
                else:
                    log.warning(
                        "SDKCameraThread: TriggerMode node not found; assuming free‐run."
                    )
            except Exception as e:
                log.warning(f"SDKCameraThread: Could not disable TriggerMode: {e}")

            # ─── 3) Signal “grabber_ready” so UI can enable “Start” button ───────
            self.grabber_ready.emit()

            # ─── 4) Build QueueSink, preferring the camera’s native PF instead of hard‐coding Mono8 ─
            # First, figure out exactly what PixelFormats the camera supports:
            native_pf_node = self.grabber.device_property_map.find_enumeration(
                "PixelFormat"
            )
            pf_list = []
            if native_pf_node:
                # Try “Mono8” first, but also add the camera’s default if Mono8 isn’t available
                all_pf_names = [entry.name for entry in native_pf_node.entries]
                if "Mono8" in all_pf_names:
                    pf_list.append(ic4.PixelFormat.Mono8)
                # fallback to whatever the camera reports as default
                default_pf_name = native_pf_node.value if native_pf_node else None
                if default_pf_name and hasattr(ic4.PixelFormat, default_pf_name):
                    pf_list.append(getattr(ic4.PixelFormat, default_pf_name))

            # If we still have no valid PF in pf_list, just try Mono8 anyway
            if not pf_list:
                pf_list = [ic4.PixelFormat.Mono8]

            try:
                self._sink = ic4.QueueSink(self, pf_list, max_output_buffers=1)
                log.info(
                    f"SDKCameraThread: Created QueueSink for PFs = {[pf.name for pf in pf_list]}"
                )
            except Exception as e:
                log.error(f"SDKCameraThread: Unable to create QueueSink: {e}")
                raise

            # ─── 5) Now start streaming (at whatever PF the QueueSink negotiated) ──────
            from imagingcontrol4 import StreamSetupOption

            try:
                self.grabber.stream_setup(
                    self._sink,
                    setup_option=StreamSetupOption.ACQUISITION_START,
                )
                log.info(
                    "SDKCameraThread: stream_setup(ACQUISITION_START) succeeded. Entering frame loop…"
                )
            except Exception as e:
                log.error(f"SDKCameraThread: Failed to start acquisition: {e}")
                # Emit error back to UI
                code_enum = getattr(e, "code", None)
                code_str = str(code_enum) if code_enum else ""
                self.error.emit(str(e), code_str)
                # Since streaming didn’t start, clean up and return:
                try:
                    self.grabber.device_close()
                    ic4.Library.exit()
                except:
                    pass
                return

            # ─── Frame loop: IC4 calls frames_queued() whenever a new buffer is ready ─
            while not self._stop_requested:
                self.msleep(10)

            # ─── Stop streaming & close device ───────────────────────────────────
            self.grabber.stream_stop()
            self.grabber.device_close()
            log.info("SDKCameraThread: Streaming stopped, device closed.")

        except Exception as e:
            msg = str(e)
            code_enum = getattr(e, "code", None)
            code_str = str(code_enum) if code_enum else ""
            log.exception("SDKCameraThread: encountered an error.")
            self.error.emit(msg, code_str)

        finally:
            try:
                ic4.Library.exit()
                log.info("SDKCameraThread: Library.exit() called.")
            except Exception:
                pass

    def frames_queued(self, sink):
        """
        This callback is invoked by IC4 each time a new buffer is available.
        Pop the buffer, convert to QImage, emit it, and allow IC4 to recycle it.
        """
        try:
            buf = sink.pop_output_buffer()
            arr = buf.numpy_wrap()  # arr: shape=(H, W) dtype=uint8 or uint16

            # Downconvert 16-bit to 8-bit if necessary
            if arr.dtype == np.uint8:
                gray8 = arr
            else:
                max_val = float(arr.max()) if arr.max() > 0 else 1.0
                scale = 255.0 / max_val
                gray8 = (arr.astype(np.float32) * scale).astype(np.uint8)

            h, w = gray8.shape[:2]

            # Build a QImage from single-channel grayscale
            qimg = QImage(gray8.data, w, h, gray8.strides[0], QImage.Format_Grayscale8)

            # ❗️ Important: copy the QImage now, before re-queueing the buffer.
            qimg_copy = qimg.copy()

            # Emit the copy to the UI
            self.frame_ready.emit(qimg_copy, buf)

            # Re-enqueue the buffer so IC4 can reuse it for the next frame
            try:
                sink.queue_buffer(buf)
            except Exception as e2:
                log.error(
                    f"SDKCameraThread.frames_queued: could not re-queue buffer: {e2}"
                )

        except Exception as e:
            log.error(
                f"SDKCameraThread.frames_queued: Error popping/converting buffer: {e}"
            )
            code_enum = getattr(e, "code", None)
            code_str = str(code_enum) if code_enum else ""
            self.error.emit(str(e), code_str)

    # ─── Required listener methods for QueueSink ─────────────────────────────
    def sink_connected(self, sink, pixel_format, min_buffers_required) -> bool:
        # Return True so the sink actually attaches
        return True

    def sink_disconnected(self, sink) -> None:
        # Called when the sink is torn down—no action needed
        pass

    def stop(self):
        """
        Request the streaming loop to end. After this, run() will clean up.
        """
        self._stop_requested = True
