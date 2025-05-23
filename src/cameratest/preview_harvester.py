#!/usr/bin/env python3
"""
preview_harvester.py

Minimal PyQt5 app to continuously grab frames from your first TIS camera
(using Harvesters) and display them in a QLabel. Exits cleanly on close.
"""

import sys
import logging
from harvesters.core import Harvester
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout
from PyQt5.QtCore import QTimer, Qt, pyqtSlot
from PyQt5.QtGui import QImage, QPixmap

# ─── EDIT THIS to match your system’s CTI path ────────────────────────────────
CTI_PATH = (
    r"C:\Program Files\The Imaging Source Europe GmbH"
    r"\IC4 GenTL Driver for USB3Vision Devices 1.4\bin\ic4-gentl-u3v_x64.cti"
)


class PreviewWidget(QWidget):
    def __init__(self, cti_path: str, device_index: int = 0, parent=None):
        super().__init__(parent)

        # QLabel for displaying the live feed
        self.label = QLabel(alignment=Qt.AlignCenter)
        self.label.setScaledContents(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)

        # Set up the Harvester + ImageAcquirer
        self.harv = Harvester()
        self.harv.add_cti_file(cti_path)
        self.harv.update()
        devices = self.harv.device_info_list
        if not devices:
            logging.error("No cameras found via Harvester!")
            sys.exit(1)
        logging.info(f"Found cameras: {[d.model_name for d in devices]}")
        self.ia = self.harv.create_image_acquirer(device_index)
        self.ia.start_acquisition()

        # Timer to pull frames as fast as possible
        self._timer = QTimer(self, interval=0)
        self._timer.timeout.connect(self._grab_frame)
        self._timer.start()

    @pyqtSlot()
    def _grab_frame(self):
        # Grab the next buffer, convert to numpy, then QImage → QPixmap
        with self.ia.fetch_buffer() as buffer:
            comp = buffer.payload.components[0]
            arr = comp.data.reshape((comp.height, comp.width))
            qimg = QImage(
                arr.data,
                comp.width,
                comp.height,
                comp.width,
                QImage.Format_Grayscale8,
            )
            pix = QPixmap.fromImage(qimg)
            self.label.setPixmap(pix)

    def closeEvent(self, event):
        # Clean shutdown: stop timer, stop acquisition, reset Harvester
        self._timer.stop()
        try:
            self.ia.stop_acquisition()
        except Exception:
            pass
        try:
            self.ia.destroy()  # if your version supports it
        except Exception:
            pass
        self.harv.reset()
        super().closeEvent(event)


def main():
    logging.basicConfig(level=logging.INFO)
    app = QApplication(sys.argv)

    preview = PreviewWidget(cti_path=CTI_PATH, device_index=0)
    preview.setWindowTitle("Camera Live Preview")
    preview.showMaximized()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
