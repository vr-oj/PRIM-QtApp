import logging
import imagingcontrol4 as ic4

log = logging.getLogger(__name__)


class IC4CameraController:
    def __init__(self):
        self.grabber = None
        self.device_opened = False
        self.device_string = "DMK 33UX250"  # Can change to UP5000 if needed
        self._init_library()
        self._init_grabber()

    def _init_library(self):
        try:
            ic4.Library.init()
            log.info("[IC4] Library initialized successfully.")
        except Exception as e:
            log.error(f"[IC4] Library initialization failed: {e}")

    def _init_grabber(self):
        try:
            self.grabber = ic4.Grabber()
            log.info("[IC4] Grabber initialized.")
        except Exception as e:
            log.error(f"[IC4] Failed to initialize Grabber: {e}")

    def open_camera(self):
        try:
            device = ic4.Device.open(self.device_string)
            self.grabber.device = device
            self.device_opened = True
            log.info(f"[IC4] Opened camera: {self.device_string}")
        except Exception as e:
            log.warning(f"[IC4] Could not open camera '{self.device_string}': {e}")
            self.device_opened = False

    def set_auto_exposure(self, enable: bool):
        if not self.device_opened:
            log.warning("[IC4] Cannot set Auto Exposure. No camera open.")
            return
        try:
            self.grabber.set_property("Exposure", "Auto", enable)
        except Exception as e:
            log.warning(f"[IC4] Failed to set Auto Exposure: {e}")

    def get_auto_exposure(self):
        if not self.device_opened:
            log.warning("[IC4] Cannot get Auto Exposure. No camera open.")
            return None
        try:
            return self.grabber.get_property("Exposure", "Auto")
        except Exception as e:
            log.warning(f"[IC4] Failed to get Auto Exposure: {e}")
            return None

    def set_property(self, category: str, name: str, value):
        if not self.device_opened:
            log.warning("[IC4] Cannot set property. No camera open.")
            return
        try:
            self.grabber.set_property(category, name, value)
        except Exception as e:
            log.warning(f"[IC4] Failed to set property {category}:{name}: {e}")

    def get_property(self, category: str, name: str):
        if not self.device_opened:
            log.warning("[IC4] Cannot get property. No camera open.")
            return None
        try:
            return self.grabber.get_property(category, name)
        except Exception as e:
            log.warning(f"[IC4] Failed to get property {category}:{name}: {e}")
            return None

    def get_property_range(self, name: str):
        if not self.device_opened:
            log.warning("[IC4] Cannot get range. No device.")
            return None
        try:
            return self.grabber.get_property_range(name)
        except Exception as e:
            log.warning(f"[IC4] Failed to get property range for {name}: {e}")
            return None
