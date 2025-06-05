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
    frame_ready(QImage, buffer). When stop() is called, stops streaming and closes.

    We have added:
      - A `frame_for_save` signal, emitted when in 'trigger' mode on each hardware pulse.
      - `set_device_info(dev_info)` & `set_resolution((w,h,pf_name))` so MainWindow can pass
        its selections in before starting this thread.
      - Two new methods: `_start_trigger_mode()` and `_stop_trigger_mode()`, which toggle
        the camera between continuous free-run and hardware-triggered single-frame mode.
    """

    # ─── Signals from the old version ───────────────────────────────────────────────
    # Emitted once the grabber is open and streaming in continuous mode
    grabber_ready = pyqtSignal()

    # Emitted whenever a new QImage is available for live preview
    frame_ready = pyqtSignal(QImage, object)

    # Emitted if any camera-related error occurs: (message, code)
    error = pyqtSignal(str, str)

    # ─── NEW: Emitted when in trigger mode and a hardware TTL arrives (NumPy array) ─
    frame_for_save = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.grabber = None
        self._sink = None

        # Old code used `_stop_requested` to break out of the loop
        self._stop_requested = False

        # Keep track of what mode we’re in: 'live' or 'trigger' or 'idle'
        self.mode = "idle"

        # Latest NumPy array (Mono8) from the camera; always updated in frames_queued()
        self.latest_frame = None

        # These will be set by MainWindow before calling start():
        self._device_info = None
        self._resolution = None  # tuple: (width, height, pixel_format_name)

    def set_device_info(self, dev_info):
        """
        Called by MainWindow to tell us which `DeviceInfo` to open.
        """
        self._device_info = dev_info

    def set_resolution(self, resolution_tuple):
        """
        Called by MainWindow to tell us which (width, height, pixel_format_name) to use.
        """
        self._resolution = resolution_tuple

    def run(self):
        """
        Main entry point of the QThread. Does exactly what the old code did:
          1) Initialize IC4 (if not already done)
          2) Verify that self._device_info is set, then open the Grabber
          3) Apply the chosen resolution (self._resolution), if provided
          4) Force continuous AcquisitionMode → Continuous
          5) Create a QueueSink (Mono8) → call grabber.stream_setup(ACQUISITION_START)
          6) Emit grabber_ready() so the UI can enable controls
          7) Enter a loop that sleeps until stop() is invoked

        We have inserted no other logic here. When in 'trigger' mode,
        _start_trigger_mode() will reconfigure the sink appropriately, and
        frames_queued() will emit frame_for_save(arr) once per TTL.
        """
        try:
            # ─── 1) Initialize the IC4 library (once per process) ───────────────────
            try:
                ic4.Library.init(
                    api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR
                )
                log.info("SDKCameraThread: Library.init() succeeded.")
            except RuntimeError as e:
                # Already initialized is fine; anything else is re-raised
                if "already called" in str(e):
                    log.info("SDKCameraThread: IC4 already initialized; continuing.")
                else:
                    raise

            # ─── 2) Ensure MainWindow gave us a DeviceInfo ─────────────────────────
            if self._device_info is None:
                raise RuntimeError("No DeviceInfo passed to SDKCameraThread.")

            # ─── 3) Open the Grabber ───────────────────────────────────────────────
            self.grabber = ic4.Grabber()
            self.grabber.device_open(self._device_info)
            log.info(
                f"SDKCameraThread: device_open() succeeded for "
                f"'{self._device_info.model_name}' (S/N '{self._device_info.serial}')."
            )

            # ─── 4) If resolution was provided, apply it (PixelFormat, Width, Height) ─
            if self._resolution:
                w, h, pf_name = self._resolution
                try:
                    # Set PixelFormat node first
                    pf_node = self.grabber.device_property_map.find_enumeration(
                        "PixelFormat"
                    )
                    if pf_node and pf_name in [entry.name for entry in pf_node.entries]:
                        pf_node.value = pf_name
                        # Then set Width & Height nodes
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

            # ─── 5) Force AcquisitionMode = Continuous ──────────────────────────────
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

            # ─── 6) Disable any trigger (so camera is free-running) ─────────────────
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
                # Ignoring errors here is fine; we just want free-run
                pass

            # ─── 7) Signal “grabber_ready” so the UI can enable controls ───────────
            self.grabber_ready.emit()

            # ─── 8) Build QueueSink requesting Mono8 (fallback if unavailable) ─────
            try:
                self._sink = ic4.QueueSink(
                    self, [ic4.PixelFormat.Mono8], max_output_buffers=1
                )
            except Exception:
                # Fall back to the native PF if Mono8 isn’t available
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

            # ─── 9) Start streaming immediately (continuous free-run) ────────────────
            from imagingcontrol4 import StreamSetupOption

            self.grabber.stream_setup(
                self._sink,
                setup_option=StreamSetupOption.ACQUISITION_START,
            )
            log.info(
                "SDKCameraThread: stream_setup(ACQUISITION_START) succeeded. Entering frame loop…"
            )

            # ─── 10) Hook the sink callbacks ───────────────────────────────────────
            self._sink.signal_frame_ready.connect(self.frames_queued)
            self.mode = "live"

            # ─── 11) Loop until stop() is called ───────────────────────────────────
            self._stop_requested = False
            while not self._stop_requested:
                self.msleep(10)

        except Exception as e:
            log.critical(f"SDKCameraThread: Exception in run(): {e}")
            self.error.emit(str(e), "RunError")

        finally:
            # ─── 12) Cleanup: stop streaming & close sink & exit IC4 ───────────
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

            log.info("SDKCameraThread: Thread exiting (continuous loop ended).")

    def stop(self):
        """
        Request that run()’s loop end.  This will cause run() to clean up and exit.
        """
        self._stop_requested = True
        self.wait()

    # ─── Required listener methods for QueueSink ────────────────────────────────────
    # These must remain exactly or IC4 will reject the sink attachment.

    def sink_connected(self, sink, pixel_format, min_buffers_required) -> bool:
        """
        Called by IC4 when a new sink is about to attach. Return True so it will attach.
        """
        return True

    def sink_disconnected(self, sink) -> None:
        """
        Called by IC4 when a sink is torn down. No action needed here.
        """
        pass

    # ─── Hardware‐Trigger (Recording) Mode Methods ──────────────────────────────────

    def _start_trigger_mode(self):
        """
        Switch from continuous (free-run) into hardware-trigger mode. Steps:
          a) Stop the current continuous sink (if any).
          b) Set AcquisitionMode = Continuous (required by IC4 to arm a FrameStart).
          c) Set TriggerSelector = FrameStart, TriggerMode = On, TriggerSource = Line0.
          d) Create a fresh QueueSink (Mono8) → stream_setup(ACQUISITION_START).
             Now the camera will capture exactly one frame per TTL rising edge.
        """
        # a) Stop continuous if it’s active
        try:
            if self._sink is not None:
                self._sink.signal_frame_ready.disconnect(self.frames_queued)
                self.grabber.stream_stop()
                self._sink.close()
                self._sink = None
        except Exception as e:
            log.error(f"SDKCameraThread: Error stopping continuous mode: {e}")

        # b) Set AcquisitionMode = Continuous
        try:
            acq_node = self.grabber.device_property_map.find_enumeration(
                "AcquisitionMode"
            )
            if acq_node and "Continuous" in [entry.name for entry in acq_node.entries]:
                acq_node.value = "Continuous"
            else:
                log.warning(
                    "SDKCameraThread: Cannot set AcquisitionMode to Continuous."
                )
        except Exception as e:
            log.error(f"SDKCameraThread: Failed to set AcquisitionMode: {e}")

        # c) Select TriggerSelector = FrameStart
        try:
            trig_sel = self.grabber.device_property_map.find_enumeration(
                "TriggerSelector"
            )
            if trig_sel and "FrameStart" in [entry.name for entry in trig_sel.entries]:
                trig_sel.value = "FrameStart"
            else:
                log.warning(
                    "SDKCameraThread: Cannot set TriggerSelector to FrameStart."
                )
        except Exception as e:
            log.error(f"SDKCameraThread: Error setting TriggerSelector: {e}")

        #    Turn TriggerMode = On
        try:
            trig_mode = self.grabber.device_property_map.find_enumeration("TriggerMode")
            if trig_mode and "On" in [entry.name for entry in trig_mode.entries]:
                trig_mode.value = "On"
            else:
                log.warning("SDKCameraThread: Cannot set TriggerMode to On.")
        except Exception as e:
            log.error(f"SDKCameraThread: Error setting TriggerMode: {e}")

        #    Set TriggerSource = Line0
        try:
            trig_src = self.grabber.device_property_map.find_enumeration(
                "TriggerSource"
            )
            if trig_src and "Line0" in [entry.name for entry in trig_src.entries]:
                trig_src.value = "Line0"
            else:
                log.warning("SDKCameraThread: Cannot set TriggerSource to Line0.")
        except Exception as e:
            log.error(f"SDKCameraThread: Error setting TriggerSource: {e}")

        # d) Arm a new QueueSink in trigger mode
        try:
            from imagingcontrol4 import StreamSetupOption

            self._sink = ic4.QueueSink(
                self, [ic4.PixelFormat.Mono8], max_output_buffers=1
            )
            self.grabber.stream_setup(
                self._sink,
                setup_option=StreamSetupOption.ACQUISITION_START,
            )
            self._sink.signal_frame_ready.connect(self.frames_queued)
            self.mode = "trigger"
            log.info("SDKCameraThread: Trigger mode armed (FrameStart on Line0).")
        except Exception as e:
            log.error(f"SDKCameraThread: Failed to start trigger mode: {e}")
            self.error.emit(str(e), "TriggerStartError")

    def _stop_trigger_mode(self):
        """
        Disable hardware-trigger mode and stop the sink. The camera becomes idle.
        """
        try:
            if self._sink is not None:
                self._sink.signal_frame_ready.disconnect(self.frames_queued)
                self.grabber.stream_stop()
                self._sink.close()
                self._sink = None
                log.info("SDKCameraThread: Trigger mode stopped.")
        except Exception as e:
            log.error(f"SDKCameraThread: Error stopping trigger mode: {e}")
        self.mode = "idle"

    # ─── Common Frame Callback ────────────────────────────────────────────────────

    def frames_queued(self, sink):
        """
        Called whenever a new buffer arrives into the active sink (live or trigger).
        Steps:
          1) pop_output_buffer() → NumPy mono8 array
          2) Save that array in self.latest_frame
          3) If mode=='trigger', emit frame_for_save(arr.copy())
          4) Convert to 8-bit QImage → emit frame_ready(qimg_copy, buf)
          5) buf.queue() to recycle
        """
        try:
            buf = sink.pop_output_buffer()
            arr = buf.numpy_wrap()  # arr: 2D Mono8 or Mono16

            # Convert Mono16→Mono8 if needed, for preview; but store raw arr
            if arr.dtype == np.uint8:
                gray8 = arr
            else:
                max_val = float(arr.max()) if arr.max() > 0 else 1.0
                scale = 255.0 / max_val
                gray8 = (arr.astype(np.float32) * scale).astype(np.uint8)

            # 1) Always update self.latest_frame with the raw 8-bit arr
            self.latest_frame = gray8.copy()

            # 2) If we’re in trigger mode, emit this array for RecordingThread
            if self.mode == "trigger":
                # Emit a COPY of the array so RecordingThread can write it immediately
                self.frame_for_save.emit(gray8.copy())

            # 3) Build QImage for live preview
            h, w = gray8.shape[:2]
            qimg = QImage(gray8.data, w, h, gray8.strides[0], QImage.Format_Grayscale8)
            qimg_copy = qimg.copy()
            self.frame_ready.emit(qimg_copy, buf)

            # 4) Re-queue the buffer so IC4 can use it again
            buf.queue()

        except Exception as e:
            log.error(f"SDKCameraThread.frames_queued error: {e}")
            # Optionally, you could also do: self.error.emit(str(e), "FrameError")
