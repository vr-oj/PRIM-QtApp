import logging
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)

class MicroManagerCameraThread(QThread):
    """Acquire frames from µManager using pymmcore-plus."""

    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str)

    def __init__(self, parent=None, config_file=None):
        super().__init__(parent)
        self._stop_requested = False
        self.core = None
        self.config_file = config_file

    def run(self):
        try:
            from pymmcore_plus import CMMCorePlus

            if not self.config_file:
                raise RuntimeError("No config file provided for µManager.")

            self.core = CMMCorePlus()
            self.core.loadSystemConfiguration(self.config_file)
            self.core.initialize_all_devices()
            self.core.waitForSystem()

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

            if self.core.isSequenceRunning():
                self.core.stopSequenceAcquisition()

        except Exception as e:
            log.error(f"MicroManagerCameraThread error: {e}")
            self.error.emit(str(e))
        finally:
            self.core = None

    def stop(self):
        self._stop_requested = True
