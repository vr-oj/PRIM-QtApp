import logging
import os
import numpy as np
from pymmcore_plus import CMMCorePlus
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class MicroManagerCameraThread(QThread):
    """Simple acquisition thread using :mod:`pymmcore_plus`."""

    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str)

    def __init__(self, parent=None, mm_path=None, config_file=None, adapter_paths=None):
        super().__init__(parent)
        self.mm_path = mm_path
        self.config_file = config_file
        self.adapter_paths = adapter_paths or []
        self.core = None
        self._stop_requested = False

    def _arr_to_qimage(self, arr: np.ndarray) -> QImage:
        h, w = arr.shape[:2]
        if arr.ndim == 2:
            return QImage(arr.data, w, h, arr.strides[0], QImage.Format_Grayscale8).copy()
        if arr.ndim == 3 and arr.shape[2] == 3:
            return QImage(arr.data, w, h, arr.strides[0], QImage.Format_RGB888).copy()
        raise ValueError("Unsupported image format")

    def run(self):
        try:
            if not self.config_file:
                raise RuntimeError("No config file provided for µManager.")

            self.core = CMMCorePlus(adapter_paths=self.adapter_paths)
            if self.mm_path:
                self.core.setDeviceAdapterSearchPaths([self.mm_path])

            self.core.loadSystemConfiguration(self.config_file)
            cam = self.core.getCameraDevice() or self.core.getLoadedDevices()[0]
            self.core.setCameraDevice(cam)
            self.core.initializeDevice(cam)
            self.core.startContinuousSequenceAcquisition(0)

            while not self._stop_requested:
                if not self.core.getRemainingImageCount():
                    self.msleep(5)
                    continue
                arr = self.core.popNextImage()
                qimg = self._arr_to_qimage(arr)
                self.frame_ready.emit(qimg, arr)

            self.core.stopSequenceAcquisition()
        except Exception as e:
            log.error(f"MicroManagerCameraThread error: {e}")
            self.error.emit(str(e))
        finally:
            if self.core is not None:
                try:
                    self.core.reset()
                    self.core.unloadAllDevices()
                except Exception:
                    pass
                self.core = None

    def stop(self):
        self._stop_requested = True
        self.wait()
