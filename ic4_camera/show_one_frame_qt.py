# show_one_frame_qt.py

import sys
import time
import imagingcontrol4 as ic4
import numpy as np

from PyQt5.QtWidgets import QApplication, QLabel, QMainWindow, QMessageBox
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import Qt


class _MinimalSinkListener(ic4.QueueSinkListener):
    def frames_queued(self, sink, *args):
        pass

    def sink_connected(self, sink, *args):
        pass


class SingleFrameWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IC4: Single Frame Preview")
        self.label = QLabel("<waiting for frame…>", alignment=Qt.AlignCenter)
        self.setCentralWidget(self.label)
        self.resize(640, 480)
        self._init_camera_and_grab()

    def _init_camera_and_grab(self):
        try:
            ic4.Library.init()
        except ic4.IC4Exception as e:
            QMessageBox.critical(self, "IC4 Error", f"Library.init() failed:\n{e}")
            sys.exit(1)

        try:
            devices = ic4.DeviceEnum.devices()
        except ic4.IC4Exception as e:
            QMessageBox.critical(
                self, "IC4 Error", f"Failed to enumerate devices:\n{e}"
            )
            sys.exit(1)

        if not devices:
            QMessageBox.critical(self, "Camera Error", "No IC4 devices found.")
            sys.exit(1)

        info = devices[0]
        try:
            self.grabber = ic4.Grabber()
            self.grabber.device_open(info)
        except ic4.IC4Exception as e:
            QMessageBox.critical(self, "IC4 Error", f"Failed to open device:\n{e}")
            sys.exit(1)

        pm = self.grabber.device_property_map
        try:
            pm.set_value(ic4.PropId.ACQUISITION_MODE, "Continuous")
            pm.set_value(ic4.PropId.ACQUISITION_FRAME_RATE, 10.0)
        except:
            pass

        listener = _MinimalSinkListener()
        self.sink = ic4.QueueSink(listener)
        self.grabber.stream_setup(
            self.sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
        )
        self.sink.alloc_and_queue_buffers(5)

        # Pop one buffer
        buf = None
        start = time.time()
        while time.time() - start < 5.0:
            try:
                buf = self.sink.try_pop_output_buffer()
            except ic4.IC4Exception:
                buf = None
            if buf is not None:
                break
            time.sleep(0.001)

        if buf is None:
            QMessageBox.critical(self, "Frame Error", "Timed out waiting for a frame.")
            self.cleanup()
            sys.exit(1)

        # Convert to NumPy
        arr = buf.numpy_wrap()
        np_img = np.array(arr, copy=False)  # shape = (H, W, C) or (H, W)

        # Release buffer ASAP
        try:
            buf.release()
        except:
            pass

        # Convert NumPy → QImage
        h, w = np_img.shape[:2]
        if np_img.dtype == np.uint16:
            # shift down to 8-bit for display
            np8 = (np_img >> 8).astype(np.uint8)
            if np8.ndim == 2:
                fmt = QImage.Format_Grayscale8
                qimg = QImage(np8.data, w, h, w, fmt)
            else:
                # assume BGR8 in 3rd channel
                rgb = np8[..., ::-1]
                bytes_per_line = 3 * w
                fmt = QImage.Format_RGB888
                qimg = QImage(rgb.data, w, h, bytes_per_line, fmt)
        elif np_img.dtype == np.uint8:
            if np_img.ndim == 2:
                fmt = QImage.Format_Grayscale8
                qimg = QImage(np_img.data, w, h, w, fmt)
            else:
                # BGR8 → convert to RGB for display
                rgb = np_img[..., ::-1]
                bytes_per_line = 3 * w
                fmt = QImage.Format_RGB888
                qimg = QImage(rgb.data, w, h, bytes_per_line, fmt)
        else:
            # fallback: take first channel as gray
            gray = (np_img[..., 0] if np_img.ndim == 3 else np_img).astype(np.uint8)
            fmt = QImage.Format_Grayscale8
            qimg = QImage(gray.data, w, h, w, fmt)

        # Show in QLabel
        pix = QPixmap.fromImage(qimg).scaled(self.label.size(), Qt.KeepAspectRatio)
        self.label.setPixmap(pix)

    def cleanup(self):
        try:
            self.grabber.acquisition_stop()
        except:
            pass
        try:
            self.grabber.device_close()
        except:
            pass


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = SingleFrameWindow()
    win.show()
    ret = app.exec_()
    win.cleanup()
    sys.exit(ret)
