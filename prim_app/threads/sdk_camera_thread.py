# sdk_camera_thread.py (partial - keep existing imports and class structure around this)
import logging
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal
import numpy as np

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    frame_ready = pyqtSignal(np.ndarray)
    camera_properties_updated = pyqtSignal(dict)
    camera_error = pyqtSignal(str)

    def __init__(self, device_serial, parent=None):
        super().__init__(parent)
        self.device_serial = device_serial
        self.device = None
        self.running = False

    def run(self):
        try:
            device = self._open_device(self.device_serial)
            if device is None:
                self.camera_error.emit("Could not open camera.")
                return

            self.device = device
            self.running = True

            # Start acquisition
            device.start_acquisition()

            # Read and emit current properties
            self._emit_current_properties()

            while self.running:
                frame = device.get_image()
                if frame is not None:
                    self.frame_ready.emit(frame)

        except Exception as e:
            log.exception("Camera thread failed")
            self.camera_error.emit(str(e))

    def stop(self):
        self.running = False
        if self.device:
            try:
                self.device.stop_acquisition()
                self.device.close()
            except Exception as e:
                log.warning(f"Error closing camera: {e}")
            self.device = None

    def _open_device(self, serial):
        for dev in ic4.Device.enumerate():
            if dev.serial == serial:
                return dev.open()
        return None

    def _emit_current_properties(self):
        props = {}
        if self.device:
            try:
                props["AutoExposure"] = self.device.get_property("ExposureAuto")
                props["Gain"] = int(self.device.get_property("Gain"))
                props["Brightness"] = int(self.device.get_property("Brightness"))
                self.camera_properties_updated.emit(props)
            except Exception as e:
                log.warning(f"Failed to read camera properties: {e}")

    def set_camera_property(self, prop_name, value):
        if not self.device:
            return
        try:
            self.device.set_property(prop_name, value)
            self._emit_current_properties()
        except Exception as e:
            log.warning(f"Failed to set {prop_name} to {value}: {e}")
