# live_preview_qt.py

import sys
import time
import imagingcontrol4 as ic4
import numpy as np

from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QMessageBox,
    QOpenGLWidget,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPainter


class _MinimalSinkListener(ic4.QueueSinkListener):
    def frames_queued(self, sink, *args):
        pass

    def sink_connected(self, sink, *args):
        pass


class GrabThread(QThread):
    """
    Grabs frames continuously from the IC4 QueueSink and emits NumPy arrays.
    """

    frame_ready = pyqtSignal(object)  # will emit a NumPy ndarray

    def __init__(self, sink, parent=None):
        super().__init__(parent)
        self.sink = sink
        self._running = False

    def run(self):
        self._running = True
        while self._running:
            try:
                buf = self.sink.try_pop_output_buffer()
            except ic4.IC4Exception as e:
                print("[GrabThread] pop error:", e)
                buf = None

            if buf is None:
                time.sleep(0.001)
                continue

            try:
                arr = buf.numpy_wrap()
                np_img = np.array(arr, copy=False)
                self.frame_ready.emit(np_img)
            except Exception as e:
                print("[GrabThread] numpy_wrap error:", e)
            finally:
                try:
                    buf.release()
                except:
                    pass

    def stop(self):
        self._running = False
        self.wait()


class VideoWidget(QOpenGLWidget):
    """
    Displays incoming NumPy frames by converting to QImage and drawing with QPainter.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_image = None

    def update_frame(self, np_img):
        if np_img is None:
            return

        h, w = np_img.shape[:2]
        c = 1 if np_img.ndim == 2 else np_img.shape[2]

        # 16-bit grayscale → downshift
        if np_img.dtype == np.uint16 and c == 1:
            arr8 = (np_img >> 8).astype(np.uint8)
            img = QImage(arr8.data, w, h, w, QImage.Format_Grayscale8)

        elif np_img.dtype == np.uint8 and c == 1:
            img = QImage(np_img.data, w, h, w, QImage.Format_Grayscale8)

        elif np_img.dtype == np.uint8 and c == 3:
            rgb = np_img[..., ::-1]  # BGR→RGB
            bytes_per_line = 3 * w
            img = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)

        elif np_img.dtype == np.uint8 and c == 4:
            rgba = np_img[..., [2, 1, 0, 3]]
            bytes_per_line = 4 * w
            img = QImage(rgba.data, w, h, bytes_per_line, QImage.Format_RGBA8888)

        else:
            # fallback: grayscale from first channel
            gray = (np_img[..., 0] if c > 1 else np_img).astype(np.uint8)
            img = QImage(gray.data, w, h, w, QImage.Format_Grayscale8)

        # Scale to widget size, keep aspect
        self.current_image = img.scaled(self.width(), self.height(), Qt.KeepAspectRatio)
        self.update()

    def paintGL(self):
        self.makeCurrent()
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.black)
        if self.current_image:
            x = (self.width() - self.current_image.width()) // 2
            y = (self.height() - self.current_image.height()) // 2
            painter.drawImage(x, y, self.current_image)
        painter.end()

    def resizeGL(self, w, h):
        if self.current_image:
            self.current_image = self.current_image.scaled(w, h, Qt.KeepAspectRatio)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IC4 Live Preview (PyQt + OpenGL)")
        self.resize(800, 600)

        # Central widget + layout
        central = QWidget()
        layout = QHBoxLayout()
        central.setLayout(layout)
        self.setCentralWidget(central)

        # Video display on left
        self.video = VideoWidget()
        layout.addWidget(self.video)

        # (We could add controls on the right later)

        # Initialize camera & start thread
        self._open_camera_and_start()

    def _open_camera_and_start(self):
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
        self.sink.alloc_and_queue_buffers(10)

        # Start worker thread to pull frames
        self.thread = GrabThread(self.sink)
        self.thread.frame_ready.connect(self.video.update_frame)
        self.thread.start()

    def closeEvent(self, event):
        # Stop thread & clean up on window close
        if hasattr(self, "thread") and self.thread:
            self.thread.stop()
        if hasattr(self, "grabber") and self.grabber:
            try:
                self.grabber.acquisition_stop()
                self.grabber.device_close()
            except:
                pass
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())
