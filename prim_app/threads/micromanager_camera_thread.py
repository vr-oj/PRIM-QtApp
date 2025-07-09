import logging
import numpy as np

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class MicroManagerCameraThread(QThread):
    """Acquire frames from µManager using pycromanager."""

    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str)

    def __init__(self, parent=None, config_file=None, headless=False):
        super().__init__(parent)
        self._stop_requested = False
        self.core = None
        self.bridge = None
        self.config_file = config_file  # optional path to MM .cfg for headless mode
        self.headless = headless

        try:
            from pycromanager import Bridge
        except ImportError:
            try:
                from pycromanager.core import Bridge  # type: ignore
            except Exception as e:  # pragma: no cover - defensive
                log.error(f"pycromanager not found or Bridge missing: {e}")
                self.Bridge = None
                self.available = False
            else:
                self.Bridge = Bridge
                self.available = True
        else:
            self.Bridge = Bridge
            self.available = True

    def run(self):
        if not self.available:
            self.error.emit("pycromanager not available")
            return

        try:
            self.bridge = self.Bridge(
                headless=self.headless, config_file=self.config_file
            )
            self.core = self.bridge.get_core()

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
                        qimg = QImage(
                            arr.data, w, h, arr.strides[0], QImage.Format_Grayscale8
                        ).copy()
                    else:
                        arr = np.reshape(img, (h, w, -1))
                        qimg = QImage(
                            arr.data, w, h, arr.strides[0], QImage.Format_RGB888
                        ).copy()

                    self.frame_ready.emit(qimg, arr)
                else:
                    self.msleep(1)

            self.core.stop_sequence_acquisition()

        except Exception as e:
            log.error(f"MicroManagerCameraThread error: {e}")
            self.error.emit(str(e))
        finally:
            if self.bridge:
                try:
                    self.bridge.close()
                except Exception:
                    pass
                self.bridge = None
            self.core = None
    def stop(self):
        self._stop_requested = True

