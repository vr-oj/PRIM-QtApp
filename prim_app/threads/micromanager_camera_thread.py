import logging
import os
import sys
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)

class MicroManagerCameraThread(QThread):
    """Acquire frames from µManager using ``pycromanager.start_headless``."""

    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str)

    def __init__(self, parent=None, mm_path=None, config_file=None):
        super().__init__(parent)
        self._stop_requested = False
        self.core = None
        self.mm_path = mm_path
        self.config_file = config_file

    def run(self):
        try:
            if not self.config_file:
                raise RuntimeError("No config file provided for µManager.")

            if self.mm_path is None:
                if getattr(sys, "frozen", False):
                    base = os.path.dirname(sys.executable)
                else:
                    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                self.mm_path = os.path.join(base, "micromanager")

            os.environ["MICROMANAGER_PATH"] = self.mm_path

            from pycromanager import start_headless

            self.core = start_headless(
                mm_app_path=self.mm_path, config_file=self.config_file
            )

            if self.core is None:
                raise RuntimeError("Failed to start µManager headless.")

            self.core.initialize_all_devices()
            self.core.wait_for_system()

            self.core.startContinuousSequenceAcquisition(0)

            while not self._stop_requested:
                if self.core.getRemainingImageCount() > 0:
                    img = self.core.popNextImage()
                    h = self.core.getImageHeight()
                    w = self.core.getImageWidth()

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
