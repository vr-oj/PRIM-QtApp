import logging
import numpy as np

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class MicroManagerCameraThread(QThread):
    """Acquire frames via a µManager instance using pycromanager Core."""

    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str)

    def __init__(self, parent=None, config_file=None):
        super().__init__(parent)
        self._stop_requested = False
        self.core = None
        self.config_file = config_file  # optional path to MM .cfg for headless mode

        try:
            from pycromanager import Core
            self.Core = Core
            self.available = True
        except ImportError as e:
            log.error(f"pycromanager not found: {e}")
            self.Core = None
            self.available = False

    def run(self):
        if not self.available:
            self.error.emit("pycromanager not available")
            return

        try:
            self.core = self.Core()

            # Optional: support standalone mode by loading a config file
            # if self.config_file:
            #     self.core.load_system_configuration(self.config_file)

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
            self.core = None

    def stop(self):
        self._stop_requested = True
