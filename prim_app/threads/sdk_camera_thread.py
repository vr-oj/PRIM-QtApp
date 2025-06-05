import logging
import numpy as np
import imagingcontrol4 as ic4
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    """
    Camera thread that:
      - Starts in continuous QueueSink mode for live preview
      - On demand (when asked by main), switches to hardware-trigger mode
        to capture one frame per Arduino pulse, then returns to live mode.
    """

    # Signals:
    #   frame_ready: emitted each time a new QImage is available for live display
    #   frame_for_save: emitted each time a camera-triggered frame arrives
    frame_ready = pyqtSignal(QImage, object)
    frame_for_save = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grabber = None
        self._sink = None
        self._running = False
        self.mode = "live"  # 'live' or 'trigger'
        self.latest_frame = None
        self._frame_counter = 0

    def run(self):
        try:
            # Initialize IC4 and open the first available device
            ic4.DeviceEnum.initialize()
            device_list = ic4.DeviceEnum.devices()
            if not device_list:
                log.error("No IC4 devices found.")
                return
            dev_info = device_list[0]
            self.grabber = ic4.Grabber()
            self.grabber.device_open(dev_info)
            log.info(f"SDKCameraThread: Opened device {dev_info.model_name}")

            # Start in continuous live mode
            self._start_continuous()
            self._running = True

            # Enter event loop; keep thread alive to handle stop requests
            while self._running:
                self.msleep(10)

        except Exception as e:
            log.error(f"SDKCameraThread: Exception in run(): {e}")
        finally:
            # Ensure cleanup
            self._stop_continuous()
            ic4.DeviceEnum.exit()
            log.info("SDKCameraThread: Exiting thread.")

    def stop(self):
        """Stop the camera thread and cleanup."""
        self._running = False
        self.wait()

    ###########################
    # Continuous (live) mode
    ###########################

    def _start_continuous(self):
        """
        Configure camera for continuous streaming with QueueSink.
        """
        # Create QueueSink for Mono8 format
        self._sink = ic4.QueueSink(self, [ic4.PixelFormat.Mono8], max_output_buffers=4)
        # Arm continuous streaming
        from imagingcontrol4 import StreamSetupOption

        self.grabber.stream_setup(
            self._sink,
            setup_option=StreamSetupOption.ACQUISITION_START,
        )
        log.info("SDKCameraThread: Continuous live mode started.")
        # Hook queue callback
        self._sink.signal_frame_ready.connect(self.frames_queued)
        self.mode = "live"

    def _stop_continuous(self):
        """
        Stop continuous streaming (QueueSink).
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

    ###############################
    # Hardware-trigger (record) mode
    ###############################

    def _start_trigger_mode(self):
        """
        Switch camera to hardware-trigger (FrameStart) mode.
        After this, each TTL pulse on the designated line yields one frame.
        """
        # Ensure any existing sink is stopped
        self._stop_continuous()

        # Set AcquisitionMode = Continuous (required to arm trigger)
        try:
            acq_mode = self.grabber.device_property_map.find_enumeration(
                "AcquisitionMode"
            )
            if acq_mode and "Continuous" in [e.name for e in acq_mode.entries]:
                acq_mode.value = "Continuous"
            else:
                log.warning(
                    "SDKCameraThread: Cannot set AcquisitionMode to Continuous."
                )
        except Exception as e:
            log.error(f"SDKCameraThread: Failed to set AcquisitionMode: {e}")

        # Select TriggerSelector = FrameStart
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

        # Turn TriggerMode = On
        try:
            trig_mode = self.grabber.device_property_map.find_enumeration("TriggerMode")
            if trig_mode and "On" in [e.name for e in trig_mode.entries]:
                trig_mode.value = "On"
            else:
                log.warning("SDKCameraThread: Cannot set TriggerMode to On.")
        except Exception as e:
            log.error(f"SDKCameraThread: Error setting TriggerMode: {e}")

        # Select TriggerSource = Line0
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

        # Arm QueueSink in trigger mode
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
        Disable hardware-trigger mode and stop sink.
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

    def frames_queued(self, sink):
        """
        Called whenever a new buffer arrives into the sink (either live or trigger).
        We convert to QImage for live preview and emit frame_for_save when in trigger mode.
        """
        try:
            buf = sink.pop_output_buffer()
            arr = buf.numpy_wrap()  # Raw NumPy array (Mono8)

            # Always update latest_frame for snapshot
            self.latest_frame = arr.copy()

            # If in trigger mode, emit this frame for saving
            if self.mode == "trigger":
                self.frame_for_save.emit(arr.copy())

            # Convert to 8-bit for QImage (safe even if arr already uint8)
            gray8 = arr if arr.dtype == np.uint8 else (arr >> 8).astype(np.uint8)
            h, w = gray8.shape
            qimg = QImage(gray8.data, w, h, gray8.strides[0], QImage.Format_Grayscale8)
            qimg_copy = qimg.copy()
            self.frame_ready.emit(qimg_copy, buf)

            buf.queue()  # Return buffer to IC4
        except Exception as e:
            log.error(f"SDKCameraThread.frames_queued error: {e}")
