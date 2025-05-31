# threads/sdk_camera_thread.py
import logging
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
import imagingcontrol4 as ic4

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    frame_ready = pyqtSignal(np.ndarray)
    camera_properties_updated = pyqtSignal(dict)
    camera_error = pyqtSignal(str)

    def __init__(self, model_hint=None, resolution_hint=None):
        super().__init__()
        self.model_hint = model_hint
        self.resolution_hint = resolution_hint
        self._stop = False
        self.device = None
        self.stream = None

    def run(self):
        log.info("Camera thread started.")
        try:
            ic4.DeviceManager.initialize()
            devices = ic4.DeviceManager.devices
            if not devices:
                raise RuntimeError("No IC4 devices found.")

            selected = devices[0]
            if self.model_hint:
                for d in devices:
                    if self.model_hint in d.name:
                        selected = d
                        break

            self.device = ic4.Device(selected)
            fmt = self.device.video_formats[0]  # fallback default
            if self.resolution_hint:
                for f in self.device.video_formats:
                    if self.resolution_hint in f.name:
                        fmt = f
                        break

            self.device.video_format = fmt
            self.stream = self.device.stream
            self.stream.start()

            while not self._stop:
                buffer = self.stream.wait_for_frame(1000)
                if buffer:
                    img = buffer.convert_to_ndarray()
                    self.frame_ready.emit(img)

        except Exception as e:
            log.error(f"Camera thread failed: {e}", exc_info=True)
            self.camera_error.emit(str(e))
        finally:
            self.stop_stream()
            log.info("Camera thread exited.")

    def stop_stream(self):
        log.info("Stopping camera stream.")
        if self.stream:
            self.stream.stop()
        if self.device:
            self.device.dispose()
        ic4.DeviceManager.dispose()
        self._stop = True
