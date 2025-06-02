# File: show_one_frame_qt.py

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
        # Return True so the sink actually connects and acquisition can start
        return True


class SingleFrameWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IC4: Single Frame Preview")
        self.label = QLabel("<Waiting for frame…>", alignment=Qt.AlignCenter)
        self.setCentralWidget(self.label)
        self.resize(640, 480)
        self._init_camera_and_grab()

    def _init_camera_and_grab(self):
        # 1) Initialize IC4 Library
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

        # 4) Query and set ExposureTime via find_float()
        try:
            prop_exp = pm.find_float(ic4.PropId.EXPOSURE_TIME)
            print("Current ExposureTime (µs):", prop_exp.value)
            # Optionally adjust: prop_exp.value = 10000.0
        except ic4.IC4Exception:
            pass

        # 5) Turn off auto‐exposure if available
        try:
            prop_auto = pm.find_boolean(ic4.PropId.EXPOSURE_AUTO)
            prop_auto.value = False
        except ic4.IC4Exception:
            pass

        # 6) Attach a QueueSink and start acquisition
        listener = MinimalListener()
        self.sink = ic4.QueueSink(listener)
        try:
            self.grabber.stream_setup(
                self.sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
        except ic4.IC4Exception as e:
            QMessageBox.critical(
                self,
                "IC4 Error",
                "stream_setup failed (sink_connected probably returned False):\n"
                + str(e),
            )
            self.grabber.device_close()
            sys.exit(1)

        # 7) Pre‐allocate buffers
        self.sink.alloc_and_queue_buffers(5)

        # 8) Pop one frame with timeout
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

        # 9) Convert ImageBuffer → NumPy
        arr = buf.numpy_wrap()
        np_img = np.array(arr, copy=False)

        # Release buffer ASAP
        try:
            buf.release()
        except:
            pass

        # 10) Convert to QImage
        h, w = np_img.shape[:2]
        if np_img.dtype == np.uint16:
            # Downshift to 8‐bit
            np8 = (np_img >> 8).astype(np.uint8)
            if np8.ndim == 2:
                fmt = QImage.Format_Grayscale8
                qimg = QImage(np8.data, w, h, w, fmt)
            else:
                # Assume BGR8 in 3rd dimension
                rgb = np8[..., ::-1]
                bytes_per_line = 3 * w
                fmt = QImage.Format_RGB888
                qimg = QImage(rgb.data, w, h, bytes_per_line, fmt)
        elif np_img.dtype == np.uint8:
            if np_img.ndim == 2:
                fmt = QImage.Format_Grayscale8
                qimg = QImage(np_img.data, w, h, w, fmt)
            else:
                # BGR8 → RGB for QImage
                rgb = np_img[..., ::-1]
                bytes_per_line = 3 * w
                fmt = QImage.Format_RGB888
                qimg = QImage(rgb.data, w, h, bytes_per_line, fmt)
        else:
            # Fallback: take first channel as grayscale
            gray = (np_img[..., 0] if np_img.ndim == 3 else np_img).astype(np.uint8)
            fmt = QImage.Format_Grayscale8
            qimg = QImage(gray.data, w, h, w, fmt)

        # 11) Display in the QLabel
        pix = QPixmap.fromImage(qimg).scaled(self.label.size(), Qt.KeepAspectRatio)
        self.label.setPixmap(pix)

    def _cleanup(self):
        """Stop acquisition and close the device."""
        try:
            self.grabber.acquisition_stop()
        except:
            pass
        try:
            self.grabber.device_close()
        except:
            pass

    def closeEvent(self, event):
        """Ensure cleanup on window close."""
        self._cleanup()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = SingleFrameWindow()
    win.show()
    ret = app.exec_()
    win._cleanup()
    sys.exit(ret)
