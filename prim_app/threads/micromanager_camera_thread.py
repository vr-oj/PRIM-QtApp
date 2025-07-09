import logging
import os
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)

class MicroManagerCameraThread(QThread):
    """Acquire frames from µManager using pycromanager's Bridge."""

    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str)

    def __init__(self, parent=None, config_file=None, mm_app_path=None):
        super().__init__(parent)
        self._stop_requested = False
        self.core = None
        self.config_file = config_file
        self.mm_app_path = mm_app_path

    def run(self):
        try:
            from utils.config import DEFAULT_MM_APP_PATH

            mm_path = (
                self.mm_app_path
                or os.environ.get("MICROMANAGER_PATH")
                or DEFAULT_MM_APP_PATH
            )
            if not mm_path:
                raise RuntimeError(
                    "µManager path not configured. Set MICROMANAGER_PATH env var"
                )

            os.environ.setdefault("MICROMANAGER_PATH", mm_path)

            from pycromanager import start_headless

            bridge = Bridge()
            self.core = bridge.get_core()

            if self.config_file and os.path.exists(self.config_file):
                self.core.loadSystemConfiguration(self.config_file)

            if self.core is None:
                raise RuntimeError(
                    "Failed to connect to µManager via Bridge. Check MICROMANAGER_PATH and config file."
                )

            self.core.initialize_all_devices()
            self.core.wait_for_system()

            self.core.start_continuous_sequence_acquisition(0)

            while not self._stop_requested:
                if self.core.get_remaining_image_count() > 0:
                    img = self.core.pop_next_image()
                    h = self.core.get_image_height()
                    w = self.core.get_image_width()

                    if img.ndim == 1:
                        arr = np.reshape(img, (h, w))
                        qimg = QImage(arr.data, w, h, arr.strides[0], QImage.Format_Grayscale8).copy()
                    else:
                        arr = np.reshape(img, (h, w, -1))
                        qimg = QImage(arr.data, w, h, arr.strides[0], QImage.Format_RGB888).copy()

                    self.frame_ready.emit(qimg, arr)
                else:
                    self.msleep(1)

            if self.core.is_sequence_running():
                self.core.stop_sequence_acquisition()

        except Exception as e:
            log.error(f"MicroManagerCameraThread error: {e}")
            self.error.emit(str(e))
        finally:
            self.core = None

    def stop(self):
        self._stop_requested = True
