# File: prim_app/threads/sdk_camera_thread.py

import logging
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    """
    A minimal thread that:
      1) Initializes IC4
      2) Opens the first available camera (using its default settings)
      3) Emits grabber_ready
      4) Waits until stop() is called, then closes and exits IC4
    """

    # Emitted once the grabber is open and ready (UI can now query self.grabber)
    grabber_ready = pyqtSignal()

    # Emitted if any error occurs: (message, code_as_string)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grabber = None
        self._stop_requested = False

    def run(self):
        try:
            # ─── 1) Initialize IC4 ──────────────────────────────────────────────
            ic4.Library.init(
                api_log_level=ic4.LogLevel.INFO,
                log_targets=ic4.LogTarget.STDERR,
            )
            log.info("SDKCameraThread: Library.init() succeeded.")

            # ─── 2) Enumerate cameras, pick the first one ───────────────────────
            devices = ic4.DeviceEnum.devices()
            if not devices:
                raise RuntimeError("No IC4 camera devices found.")
            dev_info = devices[0]
            log.info(
                f"SDKCameraThread: Opening camera {dev_info.model_name!r} (S/N {dev_info.serial!r})"
            )

            # ─── 3) Open the grabber WITHOUT changing any properties ────────────
            self.grabber = ic4.Grabber()
            self.grabber.device_open(dev_info)
            log.info(
                "SDKCameraThread: device_open() succeeded. Camera is using default settings."
            )

            # ─── 4) Emit grabber_ready so the UI knows the camera is open ──────
            self.grabber_ready.emit()

            # ─── 5) Stay alive until stop() is called ──────────────────────────
            while not self._stop_requested:
                self.msleep(100)

            # ─── 6) Close device when stop() arrives ───────────────────────────
            try:
                self.grabber.device_close()
                log.info("SDKCameraThread: device_close() succeeded.")
            except Exception:
                pass

        except Exception as e:
            # Convert e.code (if present) to string
            msg = str(e)
            code_enum = getattr(e, "code", None)
            code_str = str(code_enum) if code_enum else ""
            log.exception("SDKCameraThread: encountered an error.")
            self.error.emit(msg, code_str)

        finally:
            # Always call Library.exit() once per thread
            try:
                ic4.Library.exit()
                log.info("SDKCameraThread: Library.exit() called.")
            except Exception:
                pass

    def stop(self):
        self._stop_requested = True
