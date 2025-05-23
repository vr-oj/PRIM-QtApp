#!/usr/bin/env python3
import sys
import logging

import imagingcontrol4 as ic4
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot, Qt
from PyQt5.QtGui import QImage, QPixmap


# ─── Minimal Camera Thread ─────────────────────────────────────────────────────
class CameraThread(QThread):
    """Grabs frames continuously from a single ic4.DeviceInfo."""

    frame_ready = pyqtSignal(QImage)

    def __init__(self, device_info, parent=None):
        super().__init__(parent)
        self.device_info = device_info
        self._stop = False

    def run(self):
        # Open device
        cam = ic4.Device(self.device_info)
        sink = ic4.SnapSink(cam)
        cam.open()
        sink.open()
        # (Optional) set continuous grab mode:
        sink.start_acquisition()

        while not self._stop:
            try:
                arr = sink.snap_single()  # numpy array
                h, w = arr.shape[:2]
                # Convert to QImage (assume Mono8 for simplicity)
                img = QImage(arr.data, w, h, w, QImage.Format_Grayscale8)
                self.frame_ready.emit(img.copy())
            except Exception as e:
                logging.exception("Error grabbing frame")
                break

        # Clean up
        try:
            sink.stop_acquisition()
            sink.close()
            cam.close()
        except Exception:
            pass

    def request_stop(self):
        self._stop = True


# ─── Preview Widget ──────────────────────────────────────────────────────────────
class PreviewWidget(QWidget):
    """Simple QLabel‐based preview + clean shutdown."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.label = QLabel(alignment=Qt.AlignCenter, parent=self)
        self.label.setScaledContents(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)
        self._thread = None

    def start(self, device_info):
        if self._thread and self._thread.isRunning():
            self.stop()
        self._thread = CameraThread(device_info, parent=self)
        self._thread.frame_ready.connect(self._on_frame)
        self._thread.start()

    @pyqtSlot(QImage)
    def _on_frame(self, qimg):
        pix = QPixmap.fromImage(qimg)
        self.label.setPixmap(pix)

    def stop(self):
        if self._thread:
            self._thread.request_stop()
            self._thread.wait(2000)
            self._thread = None

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)


# ─── Main App ───────────────────────────────────────────────────────────────────
def main():
    logging.basicConfig(level=logging.DEBUG)

    # 1) Init SDK
    try:
        ic4.Library.init()
    except Exception as e:
        logging.error(f"Could not init IC4 library: {e}")
        sys.exit(1)

    # 2) Enumerate devices
    devices = ic4.Device.enumerate()
    if not devices:
        logging.error("No TIS cameras found. Exiting.")
        ic4.Library.exit()
        sys.exit(1)
    logging.info("Found cameras: %s", [d.model_name for d in devices])
    device = devices[0]

    # 3) Start Qt
    app = QApplication(sys.argv)
    win = QMainWindow()
    win.setWindowTitle(f"Camera Preview — {device.model_name}")
    preview = PreviewWidget()
    container = QWidget()
    container.setLayout(QVBoxLayout())
    container.layout().addWidget(preview)
    win.setCentralWidget(container)
    win.showMaximized()

    # 4) Kick off camera
    preview.start(device)

    # 5) Clean up on exit
    ret = app.exec_()
    preview.stop()
    try:
        ic4.Library.exit()
    except Exception:
        pass
    sys.exit(ret)


if __name__ == "__main__":
    main()
