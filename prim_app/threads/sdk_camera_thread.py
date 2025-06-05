# prim_app/threads/sdk_camera_thread.py

import logging
import numpy as np
import imagingcontrol4 as ic4
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    """
    Camera thread that:
      - Starts in continuous QueueSink mode for live preview (old behavior)
      - On demand (when asked by main_window), switches to hardware‐trigger mode
        to capture one frame per Arduino pulse (for Recording), then can switch back.
    """

    # ─── Signals copied from old version ───────────────────────────────────
    # Emitted once the grabber is opened and streaming in continuous mode
    grabber_ready = pyqtSignal()

    # Emitted whenever a new QImage is ready for the live preview
    frame_ready = pyqtSignal(QImage, object)

    # Emitted if any camera error occurs
    error = pyqtSignal(str, str)

    # ─── NEW signal added for “triggered” frame saving ────────────────────
    # Emitted when in trigger mode and a hardware TTL arrives (one NumPy array)
    frame_for_save = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)

        # Internal state:
        self.grabber = None
        self._sink = None
        self._running = False

        # Mode can be 'live', 'trigger', or 'idle'
        self.mode = "idle"

        # Latest frame buffer for snapshot/saving if needed
        self.latest_frame = None

        # To store which device & resolution the user asked for:
        self._device_info = None
        self._resolution = None  # tuple (width, height, pixel_format_name)

        # A simple counter (unused now but left here in case you need it)
        self._frame_counter = 0

    def set_device_info(self, dev_info):
        """
        Called by MainWindow to tell this thread which IC4 DeviceInfo to open.
        """
        self._device_info = dev_info

    def set_resolution(self, resolution_tuple):
        """
        Called by MainWindow to tell this thread which (w, h, pixel_format) to use.
        """
        self._resolution = resolution_tuple

    def run(self):
        """
        Main thread entry.  This does:
          1) Initialize IC4 library (if not already done)
          2) Open the chosen device (self._device_info)
          3) Set the chosen resolution (self._resolution)
          4) Start continuous streaming (QueueSink) and emit grabber_ready
          5) Enter a loop (sleeping) until stop() is called
        """
        try:
            # 1) Initialize IC4 library (only once)
            try:
                ic4.Library.init(
                    api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR
                )
                log.info("SDKCameraThread: IC4 Library.init() succeeded.")
            except RuntimeError:
                # Probably already initialized by another thread; ignore
                pass

            # 2) Make sure MainWindow gave us a device to open
            if not self._device_info:
                log.error("SDKCameraThread: No device selected. Aborting run().")
                return

            # 3) Open the device
            self.grabber = ic4.Grabber()
            self.grabber.device_open(self._device_info)
            log.info(f"SDKCameraThread: Opened device {self._device_info.model_name!r}")

            # 4) If a resolution was passed in, apply it now:
            if self._resolution:
                w, h, pf_name = self._resolution
                try:
                    # Set PixelFormat first
                    pf_node = self.grabber.device_property_map.find_enumeration(
                        "PixelFormat"
                    )
                    if pf_node and pf_name in [entry.name for entry in pf_node.entries]:
                        pf_node.value = pf_name
                        # Then set Width & Height
                        w_node = self.grabber.device_property_map.find_integer("Width")
                        h_node = self.grabber.device_property_map.find_integer("Height")
                        if w_node and h_node:
                            w_node.value = w
                            h_node.value = h
                            log.info(
                                f"SDKCameraThread: Set resolution to {w}×{h} ({pf_name})"
                            )
                        else:
                            log.warning(
                                "SDKCameraThread: Width/Height nodes not found."
                            )
                    else:
                        log.warning(
                            "SDKCameraThread: PixelFormat node not found or invalid."
                        )
                except Exception as e:
                    log.warning(f"SDKCameraThread: Failed to apply resolution: {e}")

            # 5) Start continuous live mode (old behavior)
            try:
                self._start_continuous()
            except Exception as ex:
                log.error(f"SDKCameraThread: Could not start continuous mode: {ex}")
                self.error.emit(str(ex), "ContinuousStartError")
                return

            # Notify MainWindow that streaming is live
            self.grabber_ready.emit()

            # 6) Enter a short‐sleep loop until stop() is called
            self._running = True
            while self._running:
                self.msleep(10)

        except Exception as run_ex:
            log.error(f"SDKCameraThread: Exception in run(): {run_ex}")
            self.error.emit(str(run_ex), "RunLoopError")
        finally:
            # Cleanup everything (stop streaming, exit library)
            self._stop_continuous()
            try:
                ic4.Library.exit()
            except Exception:
                pass
            log.info("SDKCameraThread: Thread exiting.")

    def stop(self):
        """
        Called from the main thread (e.g. MainWindow.closeEvent or Stop Camera button)
        to terminate this thread.  Exits the run() loop, which will in turn call
        _stop_continuous() in the finally clause.
        """
        self._running = False
        self.wait()

    # ──────────────────────────────────────────────────────────────────────────
    #                   Continuous (Live) Mode Methods
    # ──────────────────────────────────────────────────────────────────────────

    def _start_continuous(self):
        """
        Configure the camera for free‐running continuous streaming via QueueSink.
        This is exactly the same code you had before; it simply sets up the sink,
        starts acquisition, and hooks into frames_queued() for live preview.
        """
        self._sink = ic4.QueueSink(self, [ic4.PixelFormat.Mono8], max_output_buffers=4)
        from imagingcontrol4 import StreamSetupOption

        self.grabber.stream_setup(
            self._sink,
            setup_option=StreamSetupOption.ACQUISITION_START,
        )
        log.info("SDKCameraThread: Continuous live mode started.")

        # Connect the callback so each new buffer calls frames_queued()
        self._sink.signal_frame_ready.connect(self.frames_queued)
        self.mode = "live"

    def _stop_continuous(self):
        """
        Terminate continuous streaming if it is active.  Disconnects the sink,
        stops acquisition, and closes the sink handle.
        """
        try:
            if self._sink is not None:
                self._sink.signal_frame_ready.disconnect(self.frames_queued)
                self.grabber.stream_stop()
                self._sink.close()
                self._sink = None
                log.info("SDKCameraThread: Continuous live mode stopped.")
        except Exception as e:
            log.error(f"SDKCameraThread: Error stopping continuous mode: {e}")
        self.mode = "idle"

    # ──────────────────────────────────────────────────────────────────────────
    #                  Hardware‐Trigger (Recording) Mode Methods
    # ──────────────────────────────────────────────────────────────────────────

    def _start_trigger_mode(self):
        """
        Switch the camera from continuous‐stream into a hardware‐trigger‐armed state.
        In trigger mode, the camera will wait for one TTL rising edge on 'Line0',
        capture exactly one frame into the sink, and then stop until the next pulse.
        """
        # 1) If we are currently in continuous mode, shut it down
        self._stop_continuous()

        # 2) Set AcquisitionMode = Continuous so we can arm a FrameStart trigger
        try:
            acq_node = self.grabber.device_property_map.find_enumeration(
                "AcquisitionMode"
            )
            if acq_node and "Continuous" in [e.name for e in acq_node.entries]:
                acq_node.value = "Continuous"
            else:
                log.warning(
                    "SDKCameraThread: Cannot set AcquisitionMode to Continuous."
                )
        except Exception as e:
            log.error(f"SDKCameraThread: Failed to set AcquisitionMode: {e}")

        # 3) Select TriggerSelector = FrameStart
        try:
            trig_sel = self.grabber.device_property_map.find_enumeration(
                "TriggerSelector"
            )
            if trig_sel and "FrameStart" in [e.name for e in trig_sel.entries]:
                trig_sel.value = "FrameStart"
            else:
                log.warning(
                    "SDKCameraThread: Cannot set TriggerSelector to FrameStart."
                )
        except Exception as e:
            log.error(f"SDKCameraThread: Error setting TriggerSelector: {e}")

        # 4) Turn TriggerMode = On
        try:
            trig_mode = self.grabber.device_property_map.find_enumeration("TriggerMode")
            if trig_mode and "On" in [e.name for e in trig_mode.entries]:
                trig_mode.value = "On"
            else:
                log.warning("SDKCameraThread: Cannot set TriggerMode to On.")
        except Exception as e:
            log.error(f"SDKCameraThread: Error setting TriggerMode: {e}")

        # 5) Select TriggerSource = Line0 (wired to Arduino’s CamTrig pin)
        try:
            trig_src = self.grabber.device_property_map.find_enumeration(
                "TriggerSource"
            )
            if trig_src and "Line0" in [e.name for e in trig_src.entries]:
                trig_src.value = "Line0"
            else:
                log.warning("SDKCameraThread: Cannot set TriggerSource to Line0.")
        except Exception as e:
            log.error(f"SDKCameraThread: Error setting TriggerSource: {e}")

        # 6) Re‐arm a new QueueSink, but now in hardware‐trigger mode instead of free‐run
        from imagingcontrol4 import StreamSetupOption

        self._sink = ic4.QueueSink(self, [ic4.PixelFormat.Mono8], max_output_buffers=4)
        self.grabber.stream_setup(
            self._sink,
            setup_option=StreamSetupOption.ACQUISITION_START,
        )
        self._sink.signal_frame_ready.connect(self.frames_queued)
        self.mode = "trigger"
        log.info("SDKCameraThread: Trigger mode armed (FrameStart on Line0).")

    def _stop_trigger_mode(self):
        """
        Disable hardware‐trigger mode and stop the sink.  The camera goes idle.
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

    # ──────────────────────────────────────────────────────────────────────────
    #                          Common Frame Callback
    # ──────────────────────────────────────────────────────────────────────────

    def frames_queued(self, sink):
        """
        This callback is invoked whenever a new buffer arrives into the active sink
        (either in continuous live mode or in trigger mode).  We always:
          1) Pop the buffer
          2) Convert to a NumPy array
          3) Save that array into self.latest_frame
          4) If mode == 'trigger', emit frame_for_save(arr) so RecordingThread can catch it
          5) Convert to 8‐bit QImage and emit frame_ready(...) for live preview
          6) Re‐queue the buffer
        """
        try:
            buf = sink.pop_output_buffer()
            arr = buf.numpy_wrap()  # Mono8 2D array

            # 1) Always store the latest NumPy frame
            self.latest_frame = arr.copy()

            # 2) If we’re in trigger mode, emit this array so Recording can write it
            if self.mode == "trigger":
                self.frame_for_save.emit(arr.copy())

            # 3) Convert to 8‐bit QImage (arr is already Mono8, but just in case)
            gray8 = arr if arr.dtype == np.uint8 else (arr >> 8).astype(np.uint8)
            h, w = gray8.shape
            qimg = QImage(gray8.data, w, h, gray8.strides[0], QImage.Format_Grayscale8)
            qimg_copy = qimg.copy()
            self.frame_ready.emit(qimg_copy, buf)

            # 4) Return the buffer to IC4
            buf.queue()
        except Exception as e:
            log.error(f"SDKCameraThread.frames_queued error: {e}")
            # If you want to show errors to the user, you could also emit:
            # self.error.emit(str(e), "FrameCallbackError")
