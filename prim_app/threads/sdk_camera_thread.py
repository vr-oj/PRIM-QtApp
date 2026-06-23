# File: prim_app/threads/sdk_camera_thread.py

import logging
import time
import imagingcontrol4 as ic4
import numpy as np

from utils.config import DEFAULT_FPS

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
        self._frames_emitted = 0
        self._last_frame_log_time = 0.0

    def set_device_info(self, dev_info):
        self._device_info = dev_info

    def set_resolution(self, resolution_tuple):
        # resolution_tuple is (w, h, pf_name), e.g. (2448, 2048, "Mono8")
        self._resolution = resolution_tuple

    def run(self):
        self._frames_emitted = 0
        self._last_frame_log_time = 0.0
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

            # ─── Apply PixelFormat & resolution ────────────────────────────────

            # ─── DEBUG: Log all available float properties ────────────────────
            log.debug("Available float properties:")
            for p in self.grabber.device_property_map:
                try:
                    val = p.get_value()
                    log.debug(f"{p.identifier} = {val}")
                except Exception:
                    pass

            # ─── Set Default Camera Properties BEFORE Streaming ───────────────
            props = self.grabber.device_property_map
            try:
                exp_prop = props.find_float("ExposureTime")
                exp_prop.value = 10000.0  # Default to 10ms
                log.info("Set ExposureTime to 10000 µs")
            except Exception as e:
                log.warning(f"Could not set ExposureTime: {e}")
            try:
                gain_prop = props.find_float("Gain")
                gain_prop.value = 5.0
                log.info("Set Gain to 5.0")
            except Exception as e:
                log.warning(f"Could not set Gain: {e}")
            try:
                fr_node = props.find_float("AcquisitionFrameRate")
                if fr_node:
                    target_fps = min(
                        max(float(DEFAULT_FPS), float(fr_node.minimum)),
                        float(fr_node.maximum),
                    )
                    fr_node.value = target_fps
                    log.info(
                        f"SDKCameraThread: Set AcquisitionFrameRate = {target_fps}"
                    )
            except Exception as e:
                log.warning(
                    f"SDKCameraThread: Could not set AcquisitionFrameRate: {e}"
                )

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
                            "SDKCameraThread: PixelFormat node not found; using default."
                        )
                except Exception as e:
                    log.warning(f"SDKCameraThread: Could not set resolution/PF: {e}")

            # ─── Enable Auto features by default ────────────────────────────

            try:
                ae_node = self.grabber.device_property_map.find_enumeration(
                    "ExposureAuto"
                )
                if ae_node:
                    ae_node.value = "Continuous"
                    log.info("SDKCameraThread: Set ExposureAuto = Continuous")
            except Exception as e:
                log.warning(f"SDKCameraThread: Could not set ExposureAuto: {e}")

            try:
                ag_node = self.grabber.device_property_map.find_enumeration("GainAuto")
                if ag_node:
                    ag_node.value = "Continuous"
                    log.info("SDKCameraThread: Set GainAuto = Continuous")
            except Exception as e:
                log.warning(f"SDKCameraThread: Could not set GainAuto: {e}")

            # ─── Force Continuous acquisition mode ───────────────────────────────
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

            # ─── Disable trigger so camera will free‐run ─────────────────────────
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

            # ─── Signal “grabber_ready” so UI can enable controls ────────────────
            self.grabber_ready.emit()

            # ─── Build QueueSink using the listener constructor supported by IC4 1.3 ─
            self._sink = self._create_queue_sink()

            # ─── Start streaming immediately ───────────────────────────────────────
            from imagingcontrol4 import StreamSetupOption

            self.grabber.stream_setup(
                self._sink,
                setup_option=StreamSetupOption.ACQUISITION_START,
            )
            log.info(
                "SDKCameraThread: stream_setup(ACQUISITION_START) succeeded. Entering frame loop…"
            )

            # ─── Frame loop: poll QueueSink for completed frames ─────────────
            last_empty_log_time = time.monotonic()
            while not self._stop_requested:
                buf = self._pop_output_buffer(timeout_ms=250)
                if buf is None:
                    now = time.monotonic()
                    if now - last_empty_log_time >= 5.0:
                        log.warning(
                            "SDKCameraThread: stream is running but no frame buffers have arrived yet."
                        )
                        last_empty_log_time = now
                    continue
                self._emit_buffer_frame(buf)

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
            # All cleanup is handled by MainWindow once threads have stopped.
            pass

    def _create_queue_sink(self):
        """Create a QueueSink using the listener constructor supported by IC4 1.3."""
        native_pf = self._resolution[2] if self._resolution else "Mono8"
        pixel_format = ic4.PixelFormat.Mono8
        if native_pf and hasattr(ic4.PixelFormat, native_pf):
            pixel_format = getattr(ic4.PixelFormat, native_pf)

        try:
            sink = ic4.QueueSink(self, [pixel_format], max_output_buffers=5)
            log.info(
                "SDKCameraThread: QueueSink created for %s with 5 output buffers",
                native_pf,
            )
            return sink
        except Exception as e:
            log.warning(
                "SDKCameraThread: QueueSink setup for %s failed: %s; falling back to Mono8",
                native_pf,
                e,
            )
            try:
                sink = ic4.QueueSink(self, [ic4.PixelFormat.Mono8], max_output_buffers=5)
                log.info("SDKCameraThread: QueueSink created for Mono8 fallback")
                return sink
            except Exception as fallback_error:
                raise RuntimeError(
                    "SDKCameraThread: Unable to create QueueSink for preview."
                ) from fallback_error

    def _pop_output_buffer(self, timeout_ms=250):
        """Pop a completed frame buffer from the IC4 queue without busy-waiting."""
        try:
            if hasattr(self._sink, "try_pop_output_buffer"):
                buf = self._sink.try_pop_output_buffer()
                if buf is None:
                    self.msleep(10)
                return buf
            if hasattr(self._sink, "pop_output_buffer"):
                try:
                    return self._sink.pop_output_buffer(timeout_ms)
                except TypeError:
                    return self._sink.pop_output_buffer()
        except Exception as e:
            msg = str(e).lower()
            if "timeout" not in msg and "timed out" not in msg:
                log.error(f"SDKCameraThread: Error popping camera buffer: {e}")
                code_enum = getattr(e, "code", None)
                code_str = str(code_enum) if code_enum else ""
                self.error.emit(str(e), code_str)
                self._stop_requested = True
        return None

    def frames_queued(self, sink):
        """
        This callback is invoked by IC4 each time a new buffer is available.
        Pop the buffer, convert to QImage, emit it, and allow IC4 to recycle it.
        """
        buf = None
        try:
            buf = sink.pop_output_buffer()
            self._emit_buffer_frame(buf)
        except Exception as e:
            log.error(
                f"SDKCameraThread.frames_queued: Error popping/converting buffer: {e}"
            )
            code_enum = getattr(e, "code", None)
            code_str = str(code_enum) if code_enum else ""
            self.error.emit(str(e), code_str)

    def _emit_buffer_frame(self, buf):
        """Convert an IC4 image buffer to a QImage and emit it to the UI."""
        try:
            arr = buf.numpy_wrap()  # arr: shape=(H, W) dtype=uint8 or uint16

            # Downconvert 16‐bit to 8‐bit if necessary
            if arr.dtype == np.uint8:
                gray8 = arr
            else:
                max_val = float(arr.max()) if arr.max() > 0 else 1.0
                scale = 255.0 / max_val
                gray8 = (arr.astype(np.float32) * scale).astype(np.uint8)

            h, w = gray8.shape[:2]

            # Build a self-contained image before crossing thread boundaries.
            qimg = QImage(
                gray8.data, w, h, gray8.strides[0], QImage.Format_Grayscale8
            ).copy()

            # Emit to the UI
            self.frame_ready.emit(qimg, buf)
            self._frames_emitted += 1
            now = time.monotonic()
            if now - self._last_frame_log_time >= 5.0:
                log.info(
                    "SDKCameraThread: emitted %d frame(s); latest frame %dx%d dtype=%s",
                    self._frames_emitted,
                    w,
                    h,
                    gray8.dtype,
                )
                self._last_frame_log_time = now

        except Exception as e:
            log.error(
                f"SDKCameraThread: Error converting camera buffer: {e}"
            )
            code_enum = getattr(e, "code", None)
            code_str = str(code_enum) if code_enum else ""
            self.error.emit(str(e), code_str)
        finally:
            try:
                if buf is not None and hasattr(buf, "release"):
                    buf.release()
            except Exception:
                pass

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
