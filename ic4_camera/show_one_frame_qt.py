# File: show_one_frame_qt_mono8.py

import sys
import time
import imagingcontrol4 as ic4
import numpy as np

from PyQt5.QtWidgets import QApplication, QLabel, QMainWindow, QMessageBox
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import Qt


class MinimalListener(ic4.QueueSinkListener):
    def frames_queued(self, sink, *args):
        pass

    def sink_connected(self, sink, *args):
        return True  # must return True so the sink can actually attach


class SingleFrameWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IC4: Mono8 Single Frame Preview")
        self.label = QLabel("<Waiting for frame…>", alignment=Qt.AlignCenter)
        self.setCentralWidget(self.label)
        self.resize(640, 480)
        self._init_camera_and_grab()

    def _init_camera_and_grab(self):
        # 1) Initialize IC4
        try:
            ic4.Library.init()
        except ic4.IC4Exception as e:
            QMessageBox.critical(self, "IC4 Error", f"Library.init() failed:\n{e}")
            sys.exit(1)

        # 2) Enumerate devices
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

        # 3) Open Grabber
        try:
            self.grabber = ic4.Grabber()
            self.grabber.device_open(info)
        except ic4.IC4Exception as e:
            QMessageBox.critical(self, "IC4 Error", f"Failed to open device:\n{e}")
            sys.exit(1)

        pm = self.grabber.device_property_map

        # 4) Force PixelFormat = Mono8
        try:
            pi = pm.find_enumeration(ic4.PropId.PIXEL_FORMAT)
            if "Mono8" in pi.valid_value_strings:
                pi.value_string = "Mono8"
                print("Set PIXEL_FORMAT to Mono8")
            else:
                QMessageBox.critical(
                    self,
                    "PixelFormat Error",
                    "Mono8 not supported. Options: "
                    + ", ".join(pi.valid_value_strings),
                )
                self.grabber.device_close()
                sys.exit(1)
        except ic4.IC4Exception as e:
            QMessageBox.critical(
                self, "PixelFormat Error", f"Could not set PIXEL_FORMAT:\n{e}"
            )
            self.grabber.device_close()
            sys.exit(1)

        # 5) Turn off auto‐exposure if available
        try:
            prop_auto = pm.find_boolean(ic4.PropId.EXPOSURE_AUTO)
            prop_auto.value = False
        except ic4.IC4Exception:
            pass

        # 6) Attach a QueueSink but do NOT start yet
        listener = MinimalListener()
        self.sink = ic4.QueueSink(listener)
        self.grabber.stream_setup(self.sink, setup_option=ic4.StreamSetupOption.NONE)

        # 7) Pre‐allocate buffers BEFORE acquisition_start()
        self.sink.alloc_and_queue_buffers(5)

        # 8) Explicitly start acquisition
        try:
            self.grabber.acquisition_start()
        except ic4.IC4Exception as e:
            QMessageBox.critical(self, "IC4 Error", f"acquisition_start() failed:\n{e}")
            self.grabber.device_close()
            sys.exit(1)

        # 9) Pop one buffer (with a 5 s timeout)
        buf = None
        start = time.time()
        while time.time() - start < 5.0:
            try:
                buf = self.sink.try_pop_output_buffer()
            except ic4.IC4Exception as e:
                print("Error popping buffer:", e)
                break
            if buf is not None:
                break
            time.sleep(0.001)

        if buf is None:
            QMessageBox.critical(self, "Frame Error", "Timed out waiting for a frame.")
            self._cleanup()
            sys.exit(1)

        # 10) Convert ImageBuffer → NumPy
        arr = buf.numpy_wrap()
        gray8 = np.array(arr, copy=False)  # already uint8 Mono8

        # Release buffer
        try:
            buf.release()
        except:
            pass

        # 11) Convert the 8-bit grayscale array into a QImage
        h, w = gray8.shape
        fmt = QImage.Format_Grayscale8
        qimg = QImage(gray8.data, w, h, w, fmt)

        # 12) Display in the QLabel
        pix = QPixmap.fromImage(qimg).scaled(self.label.size(), Qt.KeepAspectRatio)
        self.label.setPixmap(pix)

    def _cleanup(self):
        try:
            self.grabber.acquisition_stop()
        except:
            pass
        try:
            self.grabber.device_close()
        except:
            pass

    def closeEvent(self, event):
        self._cleanup()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = SingleFrameWindow()
    win.show()
    ret = app.exec_()
    win._cleanup()
    sys.exit(ret)
