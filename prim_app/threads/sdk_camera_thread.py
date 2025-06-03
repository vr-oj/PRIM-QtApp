# File: prim_app/threads/sdk_camera_thread.py

import logging
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    grabber_ready = pyqtSignal()
    frame_ready = pyqtSignal(object, object)  # we’ll wire this up later
    error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grabber = None
        self._stop_requested = False

        # These will be set by MainWindow before start():
        self._device_info = None  # an ic4.DeviceInfo object
        self._resolution = None  # a tuple (width, height, pixel_format_name)

    def set_device_info(self, dev_info):
        """
        Called from MainWindow._on_start_stop_camera with the selected ic4.DeviceInfo.
        """
        self._device_info = dev_info

    def set_resolution(self, resolution_tuple):
        """
        Called from MainWindow._on_start_stop_camera with (w, h, pf_name).
        """
        self._resolution = resolution_tuple

    def run(self):
        try:
            # 1) Initialize IC4
            ic4.Library.init(
                api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR
            )
            log.info("SDKCameraThread: Library.init() succeeded.")

            # 2) Verify we have device_info
            if self._device_info is None:
                raise RuntimeError("No DeviceInfo passed to SDKCameraThread.")

            # 3) Open the grabber
            self.grabber = ic4.Grabber()
            self.grabber.device_open(self._device_info)
            log.info(
                f"SDKCameraThread: device_open() succeeded "
                f"for {self._device_info.model_name!r} (S/N {self._device_info.serial!r})."
            )

            # 4) If MainWindow passed a resolution, apply it now:
            if self._resolution is not None:
                w, h, pf_name = self._resolution
                try:
                    pf_node = self.grabber.device_property_map.find_enumeration(
                        "PixelFormat"
                    )
                    if pf_node:
                        pf_node.value = pf_name
                        log.info(f"SDKCameraThread: Set PixelFormat = {pf_name}")
                        w_node = self.grabber.device_property_map.find_integer("Width")
                        h_node = self.grabber.device_property_map.find_integer("Height")
                        if w_node and h_node:
                            w_node.value = w
                            h_node.value = h
                            log.info(f"SDKCameraThread: Set resolution = {w}×{h}")
                    else:
                        log.warning(
                            "SDKCameraThread: PixelFormat node not found; using camera default."
                        )
                except Exception as e:
                    log.error(f"SDKCameraThread: Failed to set resolution/PF: {e}")

            # 5) At this point, the camera is open and in the requested ULTRA‐SIMPLE “default stream” mode.
            #    We do NOT start any streaming here; we just emit grabber_ready so the UI can hook into it.
            self.grabber_ready.emit()

            # 6) Stay alive until stop() is called:
            while not self._stop_requested:
                self.msleep(100)

            # 7) Close the device when stop() arrives
            try:
                self.grabber.device_close()
                log.info("SDKCameraThread: device_close() succeeded.")
            except Exception:
                pass

        except Exception as e:
            msg = str(e)
            code_enum = getattr(e, "code", None)
            code_str = str(code_enum) if code_enum else ""
            log.exception("SDKCameraThread: encountered an error.")
            self.error.emit(msg, code_str)

        finally:
            try:
                ic4.Library.exit()
                log.info("SDKCameraThread: Library.exit() called.")
            except Exception:
                pass

    def stop(self):
        self._stop_requested = True
