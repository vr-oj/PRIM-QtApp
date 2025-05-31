import time
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
    error_occurred = pyqtSignal(str)

    def __init__(self, fps=15, parent=None):
        super().__init__(parent)
        self._fps = fps
        self._running = False
        self._device = None
        self._sink = None
        self._stream = None

    def run(self):
        log.info("Camera thread started.")
        if not IC4_AVAILABLE:
            msg = "imagingcontrol4 is not available."
            log.error(msg)
            self.error_occurred.emit(msg)
            return

        try:
            device_list = ic4.DeviceEnum.enumerate()
            if not device_list:
                msg = "No IC4 cameras found."
                log.warning(msg)
                self.error_occurred.emit(msg)
                return

            device_info = device_list[0]
            self._device = ic4.open_device(device_info)
            log.info(f"Opened device: {device_info.name} ({device_info.serial})")

            formats = ic4.get_video_formats(self._device)
            if not formats:
                msg = "No video formats found for selected camera."
                log.warning(msg)
                self.error_occurred.emit(msg)
                return

            fmt = formats[0]  # Pick the first format for now
            ic4.set_video_format(self._device, fmt)
            log.info(
                f"Set video format: {fmt.width}x{fmt.height}, {fmt.pixel_format.name}"
            )

            self._sink = ic4.create_sink()
            ic4.set_sink(self._device, self._sink)
            self._stream = ic4.get_stream(self._device)
            ic4.start_stream(self._stream)
            log.info("Camera stream started.")

            self._running = True
            delay = 1.0 / self._fps
            while self._running:
                try:
                    frame = ic4.snap(self._sink)
                    array = np.copy(frame.data)
                    self.frame_ready.emit(array)
                except Exception as frame_err:
                    log.warning(f"Frame error: {frame_err}")
                time.sleep(delay)

        except Exception as e:
            log.exception("Camera thread failed:")
            self.error_occurred.emit(str(e))
        finally:
            self._stop_stream()
            log.info("Camera thread exited.")

    def stop(self):
        log.info("Stopping camera stream.")
        self._running = False
        self.wait()

    def _stop_stream(self):
        try:
            if self._stream:
                ic4.stop_stream(self._stream)
                self._stream = None
            if self._device:
                ic4.close_device(self._device)
                self._device = None
        except Exception as cleanup_err:
            log.warning(f"Cleanup error: {cleanup_err}")
