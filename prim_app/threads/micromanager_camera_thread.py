import logging
import numpy as np

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class MicroManagerCameraThread(QThread):
    """Acquire frames via a µManager instance using pycromanager."""

    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_requested = False
        self.bridge = None
        self.core = None
        try:
            from pycromanager.bridge import Bridge
            self.Bridge = Bridge
            self.available = True
        except ImportError as e:
            log.error(f"pycromanager not found: {e}")
            self.Bridge = None
            self.available = False

    def run(self):
        if not self.available:
            self.error.emit("pycromanager not available")
            return
        try:
            self.bridge = self.Bridge()
            self.core = self.bridge.get_core()
            self.core.start_continuous_sequence_acquisition(0)
            while not self._stop_requested:
                if self.core.get_remaining_image_count() > 0:
                    tagged = self.core.pop_next_tagged_image()
                    h = int(tagged.tags.get('Height', 0))
                    w = int(tagged.tags.get('Width', 0))
                    arr = np.reshape(tagged.pix, (h, w))
                    qimg = QImage(arr.data, w, h, arr.strides[0], QImage.Format_Grayscale8).copy()
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
