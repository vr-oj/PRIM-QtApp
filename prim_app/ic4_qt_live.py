# File: ic4_qt_live.py

import sys
import time

import imagingcontrol4 as ic4
import cv2
import numpy as np

from PyQt5.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout
from PyQt5.QtCore    import Qt, pyqtSignal, pyqtSlot, QThread, QSize
from PyQt5.QtGui     import QPixmap, QImage


class GrabberThread(QThread):
    """
    QThread that opens the chosen IC4 device, sets up a QueueSink,
    calls acquisition_start(), and then continuously emits each frame
    (as a QImage) back to the main GUI thread.
    """
    frame_ready = pyqtSignal(QImage)
    error       = pyqtSignal(str, str)

    def __init__(self, dev_info, parent=None):
        super().__init__(parent)
        self.dev_info   = dev_info
        self._running   = False
        self.grabber    = None
        self.queue_sink = None

    def run(self):
        # 1) Create Grabber & open camera
        try:
            self.grabber = ic4.Grabber()
            self.grabber.device_open(self.dev_info)
        except Exception as e:
            self.error.emit(f"Could not open camera: {e}", "OPEN_ERR")
            return

        # 2) Define a small QueueSinkListener subclass
        class _Listener(ic4.QueueSinkListener):
            def __init__(self, qt_thread: "GrabberThread"):
                super().__init__()
                self.qt_thread = qt_thread

            def sink_connected(self, sink, image_type, min_buffers_required) -> bool:
                # Accept whatever buffers IC4 wants to allocate
                return True

            def frames_queued(self, sink: ic4.QueueSink):
                # Called whenever a new frame is available
                try:
                    buf = sink.pop_output_buffer()
                except Exception as pop_err:
                    # If the device was lost or timed out, emit an error
                    self.qt_thread.error.emit(f"Grab error: {pop_err}", "GRAB_ERR")
                    self.qt_thread._running = False
                    return

                # Convert the ImageBuffer to a NumPy array (in‐place BGRA8)
                arr = buf.numpy_wrap()   # shape = (height, stride)
                # Slice down to (height, width, 4):
                h, w, stride = buf.height, buf.width, buf.stride
                arr = arr.reshape((h, stride))[:, : (w * 4)].reshape((h, w, 4))

                # Example processing: blur + draw text
                cv2.blur(arr, (31, 31), arr)
                cv2.putText(
                    arr,
                    "Blurry Live Feed",
                    (50, 50),
                    fontFace=cv2.FONT_HERSHEY_SIMPLEX,
                    fontScale=1.0,
                    color=(0, 0, 255),  # red text (BGR)
                    thickness=2,
                )

                # Convert BGRA → QImage
                qimg = QImage(
                    arr.data,
                    w,
                    h,
                    stride,
                    QImage.Format.Format_BGRA8888
                ).rgbSwapped()  # swap B/R so colors appear correctly

                # Emit the QImage back to the main thread
                self.qt_thread.frame_ready.emit(qimg.copy())

                # Return the buffer back to IC4
                buf.queue_buffer()

        listener = _Listener(self)

        # 3) Create a QueueSink requesting BGRa8 output (max 2 buffers)
        #    NOTE: use PixelFormat.BGRa8 (not BGRA8)
        try:
            self.queue_sink = ic4.QueueSink(listener, [ic4.PixelFormat.BGRa8], max_output_buffers=2)
        except Exception as e:
            self.error.emit(f"Could not create QueueSink: {e}", "SINK_ERR")
            return

        # 4) Attach the sink to the grabber
        try:
            self.grabber.stream_setup(self.queue_sink)
        except Exception as e:
            self.error.emit(f"Could not set up streaming: {e}", "STREAM_ERR")
            return

        # 5) ***START ACQUISITION***  ← This was missing before
        try:
            self.grabber.acquisition_start()
        except Exception as e:
            self.error.emit(f"Could not start acquisition: {e}", "ACQ_ERR")
            return

        # 6) Enter the run‐loop so the thread doesn’t exit immediately.
        self._running = True
        while self._running:
            time.sleep(0.01)

        # 7) Cleanup: stop acquisition, stop stream, close device
        try:
            self.grabber.acquisition_stop()
        except:
            pass

        try:
            self.grabber.stream_stop()
        except:
            pass

        try:
            self.grabber.device_close()
        except:
            pass

    def stop(self):
        """Tell the thread to end its loop and wait."""
        self._running = False
        self.wait(2000)


class MainWindow(QWidget):
    """
    Simple QWidget that contains a QLabel.  Each time GrabberThread.frame_ready
    fires, we convert the QImage to a QPixmap and show it.
    """
    def __init__(self, grabber_thread: GrabberThread):
        super().__init__()
        self.grabber_thread = grabber_thread

        self.setWindowTitle("IC4 PyQt Live Demo")
        self.setFixedSize(QSize(800, 600))
        self.setLayout(QVBoxLayout())

        self.video_label = QLabel("Starting camera...", self)
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("background-color: black; color: white;")
        self.layout().addWidget(self.video_label)

        # Hook signals
        self.grabber_thread.frame_ready.connect(self.update_label)
        self.grabber_thread.error.connect(self.on_error)

        # Start the grabbing thread now that signals are connected
        self.grabber_thread.start()

    @pyqtSlot(QImage)
    def update_label(self, img: QImage):
        pix = QPixmap.fromImage(img)
        self.video_label.setPixmap(pix.scaled(
            self.video_label.size(),
            Qt.KeepAspectRatio,
            Qt.FastTransformation
        ))

    @pyqtSlot(str, str)
    def on_error(self, msg: str, code: str):
        # Show error in the QLabel and stop the thread
        self.video_label.setText(f"Error ({code}): {msg}")
        self.grabber_thread.stop()

    def closeEvent(self, event):
        # Make sure the thread stops if the window closes
        if self.grabber_thread.isRunning():
            self.grabber_thread.stop()
        super().closeEvent(event)


def main():
    # Initialize IC4 once at startup
    ic4.Library.init(api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR)

    # Choose a device from the console
    devices = ic4.DeviceEnum.devices()
    if not devices:
        print("No IC4 devices found. Exiting.")
        ic4.Library.exit()
        return

    print("Available IC4 devices:")
    for i, d in enumerate(devices):
        print(f"  [{i}] {d.model_name}  (S/N: {d.serial})  [{d.interface.display_name}]")
    idx = int(input(f"Select index [0..{len(devices)-1}]: "))
    dev_info = devices[idx]

    # Build the GrabberThread and the PyQt application
    grab_thread = GrabberThread(dev_info)
    app = QApplication(sys.argv)
    window = MainWindow(grab_thread)
    window.show()
    app.exec()

    # Clean up IC4 on exit
    ic4.Library.exit()


if __name__ == "__main__":
    main()