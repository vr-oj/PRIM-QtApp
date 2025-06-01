import logging
import imagingcontrol4 as ic4
from imagingcontrol4.library import Library

log = logging.getLogger(__name__)


class IC4CameraController:
    def __init__(self, model_hint="DMK 33"):
        self.device = None
        self.model_hint = model_hint

        try:
            Library.init()
            log.info("[IC4] Library initialized successfully.")
        except Exception as e:
            log.error(f"[IC4] Failed to initialize library: {e}")
            return

        try:
            self.grabber = ic4.grabber.Grabber()
            log.info("[IC4] Grabber initialized.")
        except Exception as e:
            log.error(f"[IC4] Failed to initialize Grabber: {e}")
            return

    def open_camera(self):
        """Open the first available IC4 camera matching the model hint."""
        try:
            devices = self.grabber.get_available_video_capture_devices()
        except Exception as e:
            log.error(f"[IC4] Failed to get available devices: {e}")
            return False

        if not devices:
            log.warning("[IC4] No compatible devices found.")
            return False

        for dev in devices:
            if self.model_hint.lower() in dev.name.lower():
                try:
                    self.grabber.open(dev)
                    self.device = self.grabber.get_device()
                    log.info(f"[IC4] Camera opened: {dev.name}")
                    return True
                except Exception as e:
                    log.error(f"[IC4] Failed to open camera: {e}")
                    return False

        log.warning(f"[IC4] No matching device for model hint: {self.model_hint}")
        return False

    def close_camera(self):
        try:
            self.grabber.close()
            log.info("[IC4] Camera closed.")
            self.device = None
        except Exception as e:
            log.warning(f"[IC4] Error while closing camera: {e}")

    def set_property(self, name: str, value):
        if not self.device:
            log.warning("[IC4] Cannot set property. No camera open.")
            return
        try:
            prop = self.device[name]
            prop.value = value
            log.debug(f"[IC4] Set {name} → {value}")
        except Exception as e:
            log.error(f"[IC4] Failed to set {name}: {e}")

    def get_property(self, name: str):
        if not self.device:
            log.warning("[IC4] Cannot get property. No camera open.")
            return None
        try:
            value = self.device[name].value
            log.debug(f"[IC4] {name} = {value}")
            return value
        except Exception as e:
            log.error(f"[IC4] Failed to get {name}: {e}")
            return None

    def get_all_properties(self):
        if not self.device:
            return {}

        props = {}
        for name in ["Gain", "Exposure", "Auto Exposure", "Brightness", "Frame Rate"]:
            try:
                props[name] = self.device[name].value
            except Exception as e:
                log.warning(f"[IC4] Property '{name}' unavailable: {e}")
        return props

    # NEW METHODS
    def set_auto_exposure(self, enabled: bool):
        """Enable or disable auto exposure using IC4 SDK."""
        try:
            prop = self.device["Exposure Auto"]
            if prop:
                prop.value = "Continuous" if enabled else "Off"
                log.debug(f"[IC4] Auto Exposure set to: {'ON' if enabled else 'OFF'}")
        except Exception as e:
            log.warning(f"[IC4] Failed to set Auto Exposure: {e}")

    def set_gain(self, value: float):
        """Set camera gain using IC4 SDK."""
        try:
            prop = self.device["Gain"]
            if prop:
                prop.value = value
                log.debug(f"[IC4] Gain set to: {value}")
        except Exception as e:
            log.warning(f"[IC4] Failed to set Gain: {e}")

    def get_camera_properties(self):
        """Return a dict of current camera property values."""
        props = {}
        for name in ["Gain", "Exposure Time (us)", "Exposure Auto"]:
            try:
                props[name] = self.device[name].value
            except Exception as e:
                log.warning(f"[IC4] Failed to read '{name}': {e}")
        return props

    def get_auto_exposure(self):
        if not self.device:
            return False
        try:
            return bool(self.device["Auto Exposure"].value)
        except Exception as e:
            log.warning(f"[IC4] Failed to get Auto Exposure state: {e}")
            return False
