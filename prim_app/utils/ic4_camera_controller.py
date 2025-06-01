# prim_app/utils/ic4_camera_controller.py

import logging
import imagingcontrol4 as ic4

log = logging.getLogger(__name__)


class IC4CameraController:
    def __init__(self, model_hint="DMK 33"):
        self.device = None
        self.model_hint = model_hint

        # Ensure library is initialized
        try:
            ic4.library.init()
            log.info("[IC4] Library initialized.")
        except Exception as e:
            log.error(f"[IC4] Failed to initialize library: {e}")

    def open_camera(self):
        """Open the first available camera that matches the model hint."""
        try:
            devices = ic4.devenum.get_device_list()
        except Exception as e:
            log.error(f"[IC4] Failed to get device list: {e}")
            return False

        if not devices:
            log.warning("No IC4-compatible cameras found.")
            return False

        for dev_info in devices:
            if self.model_hint.lower() in dev_info.name.lower():
                try:
                    self.device = dev_info.open_device()
                    log.info(f"[IC4] Device opened: {dev_info.name}")
                    return True
                except Exception as e:
                    log.error(f"[IC4] Failed to open device: {e}")
                    return False

        log.warning(f"No camera matched model hint: {self.model_hint}")
        return False

    def close_camera(self):
        if self.device:
            try:
                self.device.close()
                log.info("IC4 device closed.")
            except Exception as e:
                log.warning(f"[IC4] Error while closing camera: {e}")
            self.device = None

    def set_property(self, name: str, value):
        if not self.device:
            log.warning("Attempted to set property with no IC4 device open.")
            return
        try:
            prop = self.device[name]
            prop.value = value
            log.debug(f"[IC4] Set {name} to {value}")
        except Exception as e:
            log.error(f"[IC4] Failed to set {name}: {e}")

    def get_property(self, name: str):
        if not self.device:
            log.warning("Attempted to get property with no IC4 device open.")
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
                log.warning(f"[IC4] Property '{name}' not available: {e}")
        return props
