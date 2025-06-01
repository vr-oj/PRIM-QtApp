import logging
import imagingcontrol4 as ic4
from imagingcontrol4.library import Library  # <-- Add this import

log = logging.getLogger(__name__)


class IC4CameraController:
    def __init__(self, model_hint="DMK 33"):
        self.device = None
        self.model_hint = model_hint

        try:
            Library.init()  # <-- REQUIRED init before using Grabber
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
