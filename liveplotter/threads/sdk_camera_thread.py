# sdk_camera_thread.py

import logging
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

try:
    import imagingcontrol4 as ic4

    IC4_AVAILABLE = True
except ImportError:
    IC4_AVAILABLE = False

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    frame_ready = pyqtSignal(np.ndarray)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = False
        self.device = None
        self.stream = None
        self.sink = None
        self.selected_device_name = None  # Could be used for multiple camera support

    def run(self):
        log.info("Camera thread started.")
        if not IC4_AVAILABLE:
            log.error("imagingcontrol4 module not available.")
            return

        try:
            devices = ic4.Device.enumerate()
            if not devices:
                raise RuntimeError("No IC Imaging Source devices found.")

            self.device = devices[0].open()
            fmt = self.device.videoFormats()[0]
            self.device.setVideoFormat(fmt)
            self.sink = self.device.sink()
            self.stream = self.device.stream()
            self.running = True
            self.stream.start()

            while self.running:
                frame = self.sink.snap()
                if frame:
                    array = np.array(frame, copy=True)
                    self.frame_ready.emit(array)

        except Exception as e:
            log.error(f"Camera thread failed: {e}", exc_info=True)
        finally:
            self.cleanup()

    def stop(self):
        log.info("Stopping camera stream.")
        self.running = False

    def cleanup(self):
        try:
            if self.stream:
                self.stream.stop()
            if self.device:
                self.device.close()
        except Exception as e:
            log.warning(f"Error during camera cleanup: {e}")
        log.info("Camera thread exited.")
