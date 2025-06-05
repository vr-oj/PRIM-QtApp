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
    then starts a QueueSink‐based stream. Each new frame is emitted as a QImage via
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
        self.grabber: ic4.Grabber | None = None
        self._stop_requested = False

        # Will be set by MainWindow before start():
        self._device_info: ic4.DeviceInfo | None = None
        # resolution_tuple is (width, height, pixel_format_name)
        self._resolution: tuple[int, int, str] | None = None

        # Keep a reference to the sink so we can stop it later
        self._sink: ic4.QueueSink | None = None

    def set_device_info(self, dev_info: ic4.DeviceInfo):
        self._device_info = dev_info

    def set_resolution(self, resolution_tuple: tuple[int, int, str]):
        """
        resolution_tuple: (width, height, pixel_format_name).
        Pixel format name must exactly match one of the camera’s valid enumeration entries.
        """
        self._resolution = resolution_tuple

    def run(self):
        try:
            # ─── Initialize IC4 (with “already called” catch) ─────────────────
            try:
                ic4.Library.init(
                    api_log_level=ic4.LogLevel.INFO,
                    log_targets=ic4.LogTarget.STDERR,
                )
                log.info("SDKCameraThread: Library.init() succeeded.")
            except RuntimeError as e:
                if "already called" in str(e):
                    log.info("SDKCameraThread: IC4 already initialized; continuing.")
                else:
                    raise

            # ─── Verify device_info was set ───────────────────────────────────
            if self._device_info is None:
                raise RuntimeError("No DeviceInfo passed to SDKCameraThread.")

            # ─── Open the grabber ──────────────────────────────────────────────
            self.grabber = ic4.Grabber()
            self.grabber.device_open(self._device_info)
            log.info(
                f"SDKCameraThread: device_open() succeeded for "
                f"'{self._device_info.model_name}' (S/N '{self._device_info.serial}')."
            )

            # ─── Apply PixelFormat & resolution (if provided) ─────────────────
            if self._resolution is not None:
                w, h, pf_name = self._resolution

                # 1) Find the PixelFormat enumeration node
                pf_node: ic4.PropEnumeration | None = (
                    self.grabber.device_property_map.find_enumeration("PixelFormat")
                )
                if pf_node:
                    # 2) Collect all valid entry names
                    valid_pf_names = [entry.name for entry in pf_node.entries]

                    if pf_name not in valid_pf_names:
                        log.warning(
                            f"SDKCameraThread: Requested PixelFormat={pf_name!r} is not valid. "
                            f"Valid options are: {valid_pf_names}. Skipping PF assignment."
                        )
                    else:
                        try:
                            pf_node.value = pf_name
                            log.info(f"SDKCameraThread: Set PixelFormat = {pf_name!r}")
                        except ic4.IC4Exception as e:
                            log.error(
                                f"SDKCameraThread: Failed to set PixelFormat to {pf_name!r}: "
                                f"{e.code}, {e.message}"
                            )

                        # 3) Only after PF is set do we set Width/Height
                        w_node: ic4.PropInteger | None = (
                            self.grabber.device_property_map.find_integer("Width")
                        )
                        h_node: ic4.PropInteger | None = (
                            self.grabber.device_property_map.find_integer("Height")
                        )
                        if w_node and h_node:
                            try:
                                w_node.value = w
                                h_node.value = h
                                log.info(f"SDKCameraThread: Set resolution = {w}×{h}")
                            except ic4.IC4Exception as e:
                                log.warning(
                                    f"SDKCameraThread: Could not set resolution {w}×{h}: "
                                    f"{e.code}, {e.message}"
                                )
                        else:
                            log.warning(
                                "SDKCameraThread: Could not find Width/Height properties after PF assignment."
                            )
                else:
                    log.warning(
                        "SDKCameraThread: PixelFormat node not found; using camera default."
                    )

            # ─── Force Continuous acquisition mode ─────────────────────────────
            try:
                acq_node: ic4.PropEnumeration | None = (
                    self.grabber.device_property_map.find_enumeration("AcquisitionMode")
                )
                if acq_node:
                    entries = [e.name for e in acq_node.entries]
                    if "Continuous" in entries:
                        acq_node.value = "Continuous"
                        log.info("SDKCameraThread: Set AcquisitionMode = Continuous")
                    else:
                        acq_node.value = entries[0]
                        log.info(f"SDKCameraThread: Set AcquisitionMode = {entries[0]}")
                else:
                    log.warning(
                        "SDKCameraThread: Could not find AcquisitionMode; proceeding."
                    )
            except Exception as e:
                log.warning(f"SDKCameraThread: Could not set AcquisitionMode: {e}")

            # ─── Disable trigger so camera will free‐run ────────────────────────
            try:
                trig_node: ic4.PropEnumeration | None = (
                    self.grabber.device_property_map.find_enumeration("TriggerMode")
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

            # ─── Signal “grabber_ready” so UI can enable controls ───────────────
            self.grabber_ready.emit()

            # ─── Build QueueSink requesting Mono8 (fallback to native PF if needed)─
            try:
                self._sink = ic4.QueueSink(
                    self, [ic4.PixelFormat.Mono8], max_output_buffers=8
                )
                log.info(
                    "SDKCameraThread: Created QueueSink for PFs = ['Mono8'], max_output_buffers=8"
                )
            except Exception:
                # If Mono8 is not available, fall back to the camera’s native PF:
                native_pf = self._resolution[2] if self._resolution else None
                if native_pf and hasattr(ic4.PixelFormat, native_pf):
                    pf_enum_value = getattr(ic4.PixelFormat, native_pf)
                    self._sink = ic4.QueueSink(
                        self, [pf_enum_value], max_output_buffers=8
                    )
                    log.info(
                        f"SDKCameraThread: Fallback QueueSink created for native PF = {native_pf!r}, max_output_buffers=8"
                    )
                else:
                    raise RuntimeError(
                        "SDKCameraThread: Unable to create QueueSink for Mono8 or native PF."
                    )

            # ─── Start streaming immediately ───────────────────────────────────
            from imagingcontrol4 import StreamSetupOption

            self.grabber.stream_setup(
                self._sink,
                setup_option=StreamSetupOption.ACQUISITION_START,
            )
            log.info(
                "SDKCameraThread: stream_setup(ACQUISITION_START) succeeded. Entering frame loop…"
            )

            # ─── Frame loop: IC4 calls frames_queued() whenever a new buffer is ready ─
            while not self._stop_requested:
                self.msleep(10)

            # ─── Stop streaming & close device ─────────────────────────────────
            if self.grabber.is_streaming:
                self.grabber.stream_stop()
            if self.grabber.is_device_open:
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

    def frames_queued(self, sink: ic4.QueueSink):
        """
        This callback is invoked by IC4 each time a new buffer is available.
        We pop all available buffers (keeping only the very newest), convert it to QImage,
        emit it to the UI, then call buf.queue_buffer() so IC4 can reuse them.
        """
        try:
            # 1) Pop the first buffer → treat as 'latest_buf' initially
            latest_buf: ic4.ImageBuffer = sink.pop_output_buffer()

            # 2) Drain any other buffers, immediately returning them
            while True:
                try:
                    older: ic4.ImageBuffer = sink.pop_output_buffer(timeout=0)
                    older.queue_buffer()
                except Exception:
                    # No more buffers available
                    break

            # 3) 'latest_buf' is now truly the freshest buffer
            arr = (
                latest_buf.numpy_wrap()
            )  # shape=(H, W, 1) or (H, W, 3), dtype=uint8/uint16

            # 4) Convert to 8‐bit grayscale if needed (Mono8 cameras skip this)
            if arr.dtype == np.uint8:
                gray8 = (
                    arr[..., 0] if arr.ndim == 3 else arr
                )  # strip channel dimension if present
            else:
                # find max, scale into [0..255]
                max_val = float(arr.max()) if arr.max() > 0 else 1.0
                scale = 255.0 / max_val
                gray8 = (arr.astype(np.float32) * scale).astype(np.uint8)
                gray8 = gray8[..., 0] if gray8.ndim == 3 else gray8

            h, w = gray8.shape[:2]

            # 5) Build a QImage from single‐channel grayscale
            qimg = QImage(
                gray8.data,
                w,
                h,
                gray8.strides[0],
                QImage.Format_Grayscale8,
            )
            qimg_copy = qimg.copy()  # copy before returning the buffer

            # 6) Emit only the newest frame to the UI
            self.frame_ready.emit(qimg_copy, latest_buf)

            # 7) Return the newest buffer to IC4
            latest_buf.queue_buffer()

        except Exception as e:
            log.error(
                f"SDKCameraThread.frames_queued: error popping/converting buffer: {e}"
            )
            code_enum = getattr(e, "code", None)
            code_str = str(code_enum) if code_enum else ""
            self.error.emit(str(e), code_str)

    # ─── “Listener” methods for QueueSink ────────────────────────────────
    # We implement these two methods; IC4 will detect them by duck-typing,
    # so we do not need to explicitly inherit from QueueSinkListener.

    def sink_connected(
        self, sink: ic4.QueueSink, pixel_format, min_buffers_required
    ) -> bool:
        # Return True so the QueueSink actually attaches
        return True

    def sink_disconnected(self, sink: ic4.QueueSink) -> None:
        # Called when the sink is torn down—no action needed
        pass

    def stop(self):
        """
        Request the streaming loop to end. After this, run() will clean up.
        """
        self._stop_requested = True
