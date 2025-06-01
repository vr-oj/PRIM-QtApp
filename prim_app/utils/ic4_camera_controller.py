import logging
import imagingcontrol4 as ic4

log = logging.getLogger(__name__)


class IC4CameraController:
    PROPERTY_NAME_MAP = {
        "AutoExposure": "Auto Exposure",
        "Gain": "Gain",
        "Exposure": "Exposure",
        "Brightness": "Brightness",
        "FrameRate": "Frame Rate",
    }

    def __init__(self, model_hint="DMK 33"):
        self.device = None
        self.model_hint = model_hint

        try:
            ic4.Library.init()
        except Exception as e:
            log.error(f"[IC4] Failed to initialize library: {e}")

    def _resolve_property_name(self, name: str):
        return self.PROPERTY_NAME_MAP.get(name, name)

    def is_ready(self):
        return self.device is not None

    def open_camera(self):
        """Open the first available camera that matches the model hint."""
        devices = ic4.Device.enumerate()
        if not devices:
            log.error("No IC4-compatible devices found.")
            return False

        for dev_info in devices:
            if self.model_hint.lower() in dev_info.name.lower():
                self.device = dev_info.open_device()
                log.info(f"[IC4] Device opened: {dev_info.name}")
                return True

        log.warning("[IC4] No matching IC4 camera found.")
        return False

    def close_camera(self):
        if self.device:
            self.device.close()
            log.info("[IC4] Device closed.")
            self.device = None

    def set_property(self, name: str, value):
        """Set a camera property via IC4."""
        if not self.device:
            log.warning("[IC4] Cannot set property; device not open.")
            return

        resolved = self._resolve_property_name(name)
        try:
            prop = self.device[resolved]
            prop.value = value
            log.debug(f"[IC4] Set {resolved} to {value}")
        except Exception as e:
            log.error(f"[IC4] Failed to set {resolved}: {e}")

    def get_property(self, name: str):
        """Retrieve a camera property value via IC4."""
        if not self.device:
            log.warning("[IC4] Cannot get property; device not open.")
            return None

        resolved = self._resolve_property_name(name)
        try:
            value = self.device[resolved].value
            log.debug(f"[IC4] {resolved} = {value}")
            return value
        except Exception as e:
            log.error(f"[IC4] Failed to get {resolved}: {e}")
            return None

    def get_all_properties(self):
        """Fetch a dictionary of commonly used camera properties."""
        if not self.device:
            return {}

        props = {}
        for key in self.PROPERTY_NAME_MAP.values():
            try:
                props[key] = self.device[key].value
            except Exception as e:
                log.warning(f"[IC4] Property '{key}' not available: {e}")
        return props

    def set_auto_exposure(self, enabled: bool):
        """Convenience method for AE control."""
        self.set_property("AutoExposure", bool(enabled))
