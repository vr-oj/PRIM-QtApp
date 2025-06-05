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
        # We keep it for potential future use, but we will not force‐apply it here.
        self._resolution = resolution_tuple

    def run(self):
        try:
            # ─── 1) Initialize IC4 (with “already called” catch) ─────────────────
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

            # ─── 2) Verify device_info was set ───────────────────────────────────
            if self._device_info is None:
                raise RuntimeError("No DeviceInfo passed to SDKCameraThread.")

            # ─── 3) Open the grabber ──────────────────────────────────────────────
            self.grabber = ic4.Grabber()
            self.grabber.device_open(self._device_info)
            log.info(
                f"SDKCameraThread: device_open() succeeded for "
                f"'{self._device_info.model_name}' (S/N '{self._device_info.serial}')."
            )

            # ─── 4) Build QueueSink (before any GenICam settings) ─────────────────
            native_pf_node = self.grabber.device_property_map.find_enumeration(
                "PixelFormat"
            )
            pf_list = []

            if native_pf_node:
                # Get the camera’s supported PF names
                all_pf_names = [entry.name for entry in native_pf_node.entries]

                # a) If “Mono8” is supported, add it first
                if "Mono8" in all_pf_names:
                    pf_list.append(ic4.PixelFormat.Mono8)

                # b) Determine the camera’s current/default PF name
                default_pf_name = native_pf_node.value if native_pf_node else None

                # c) If default PF is not “Mono8” (and is valid), add it
                if (
                    default_pf_name
                    and default_pf_name != "Mono8"
                    and hasattr(ic4.PixelFormat, default_pf_name)
                ):
                    pf_list.append(getattr(ic4.PixelFormat, default_pf_name))

            # d) If pf_list is still empty, fall back to Mono8
            if not pf_list:
                pf_list = [ic4.PixelFormat.Mono8]

            try:
                self._sink = ic4.QueueSink(self, pf_list, max_output_buffers=8)
                names = [pf.name for pf in pf_list]
                log.info(f"SDKCameraThread: Created QueueSink for PFs = {names}")
            except Exception as e:
                log.error(f"SDKCameraThread: Unable to create QueueSink: {e}")
                raise

            # ─── 5) Force Continuous acquisition mode ───────────────────────────────
            #    (Doing this _after_ sink creation helps avoid negotiation hangups)
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

            # ─── 6) Disable trigger so camera will free‐run ─────────────────────────
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

            # ─── 7) Signal “grabber_ready” so UI can enable controls ───────────────
            self.grabber_ready.emit()

            # ─── 8) Now start streaming ───────────────────────────────────────────
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
                # Cleanup and exit
                try:
                    self.grabber.device_close()
                    ic4.Library.exit()
                except:
                    pass
                return

            # ─── 9) Frame loop: IC4 calls frames_queued() whenever a new buffer is ready ─
            while not self._stop_requested:
                self.msleep(10)

            # ─── 10) Stop streaming & close device ──────────────────────────────────
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
        try:
            # 1) Pop all queued buffers until only the newest one remains
            latest_buf = sink.pop_output_buffer()
            while True:
                try:
                    # Keep popping until there are no more buffers
                    older = sink.pop_output_buffer(timeout=0)
                    # We don't convert 'older'; we just return it so IC4 can reuse it
                    sink.queue_buffer(older)
                except Exception:
                    break

            # 'latest_buf' is now the freshest buffer
            arr = latest_buf.numpy_wrap()
            # ...convert as before...
            if arr.dtype == np.uint8:
                gray8 = arr
            else:
                max_val = float(arr.max()) if arr.max() > 0 else 1.0
                scale = 255.0 / max_val
                gray8 = (arr.astype(np.float32) * scale).astype(np.uint8)

            h, w = gray8.shape[:2]
            qimg = QImage(gray8.data, w, h, gray8.strides[0], QImage.Format_Grayscale8)
            qimg_copy = qimg.copy()

            # 2) Emit only the latest frame
            self.frame_ready.emit(qimg_copy, latest_buf)

            # 3) Re-queue the latest buffer so IC4 can reuse it
            sink.queue_buffer(latest_buf)

        except Exception as e:
            log.error(f"frames_queued error: {e}")
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
