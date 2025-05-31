import logging
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker
from PyQt5.QtGui import QImage

import imagingcontrol4 as ic4

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    frame_ready = pyqtSignal(QImage, object)  # QImage and raw buffer

    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = False
        self.device = None
        self.stream = None
        self.sink = None
        self.frame_mutex = QMutex()

    def run(self):
        log.info("Camera thread started.")
        try:
            devices = ic4.Device.enumerate()
            if not devices:
                log.error("No IC4 cameras found.")
                return

            self.device = devices[0].open()
            self.device.setVideoFormat(self.device.videoFormats()[0])
            self.sink = self.device.sink()
            self.stream = self.device.stream()
            self.stream.start()
            self.running = True

            while self.running:
                buffer = self.sink.snap()
                if not buffer or buffer.isEmpty():
                    continue

                width, height = buffer.width(), buffer.height()
                data = buffer.data()
                img_array = np.frombuffer(data, dtype=np.uint8).reshape((height, width))

                image = QImage(
                    img_array.data,
                    width,
                    height,
                    QImage.Format_Grayscale8,
                ).copy()

                self.frame_ready.emit(image, buffer)

        except Exception as e:
            log.exception(f"Camera thread failed: {e}")
        finally:
            self.cleanup()

    def stop(self):
        with QMutexLocker(self.frame_mutex):
            self.running = False
        self.wait()

    def cleanup(self):
        log.info("Stopping camera stream.")
        try:
            if self.stream:
                self.stream.stop()
        except Exception:
            log.warning("Failed to stop stream cleanly.")
        try:
            if self.device:
                self.device.close()
        except Exception:
            log.warning("Failed to close camera device.")
        log.info("Camera thread exited.")
