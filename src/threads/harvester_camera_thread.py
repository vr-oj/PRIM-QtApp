import logging
from harvesters.core import Harvester
from PyQt5.QtCore import QThread, pyqtSignal

log = logging.getLogger(__name__)


class HarvesterCameraThread(QThread):
    """Grab frames via Harvesters and emit QImage + raw data."""

    frame_ready = pyqtSignal(object, object)  # (QImage, numpy array)
    error = pyqtSignal(str, str)

    def __init__(self, cti_path: str, device_index: int = 0, parent=None):
        super().__init__(parent)
        self._stop = False
        self.cti_path = cti_path
        self.device_index = device_index

    def run(self):
        try:
            harv = Harvester()
            harv.add_file(self.cti_path)
            harv.update()
            ia = harv.create(self.device_index)
            ia.start()
        except Exception as e:
            log.exception("Failed to init Harvester")
            self.error.emit(str(e), "")
            return

        while not self._stop:
            try:
                with ia.fetch() as buffer:
                    comp = buffer.payload.components[0]
                    arr = comp.data.reshape((comp.height, comp.width))
                    # convert to QImage
                    from PyQt5.QtGui import QImage

                    img = QImage(
                        arr.data,
                        comp.width,
                        comp.height,
                        comp.width,
                        QImage.Format_Grayscale8,
                    ).copy()
                    self.frame_ready.emit(img, arr)
            except Exception as e:
                log.exception("Error grabbing frame")
                self.error.emit(str(e), "")
                break

        try:
            ia.stop()
            ia.destroy()
            harv.reset()
        except:
            pass

    def request_stop(self):
        self._stop = True
