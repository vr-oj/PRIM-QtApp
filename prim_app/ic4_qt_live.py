# File: ic4_qt_live.py
# -------------------------------------------
# Minimal PyQt5 + IC4 example: continuously grab frames,
# optionally process them with OpenCV, and display them in a QLabel.
#
# Usage:   python ic4_qt_live.py
#            → Choose camera index from console prompt.
#            → A small window appears showing a live, blurred feed.
#            → Close the window to exit.
# -------------------------------------------

import sys
import time

import imagingcontrol4 as ic4
import cv2
import numpy as np

from PyQt5.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout
from PyQt5.QtCore    import Qt, pyqtSignal, QObject, QThread, QSize
from PyQt5.QtGui     import QPixmap, QImage

#
# 1) This tiny helper thread class will run the IC4 streaming loop
#    and emit a Qt signal for each new frame (as a QImage).
#
class GrabberThread(QThread):
    frame_ready = pyqtSignal(QImage)     # we’ll emit a QImage to the main GUI
    error       = pyqtSignal(str, str)   # in case something goes wrong

    def __init__(self, dev_info, parent=None):
        super().__init__(parent)
        self.dev_info = dev_info
        self._running = False
        self.grabber  = None
        self.queue_sink = None

    def run(self):
        """
        Called when thread.start() is invoked.
        We:
          (1) Create Grabber and open the chosen DeviceInfo.
          (2) Build a QueueSink + Listener, then start streaming.
        """
        try:
            # (1) Create and open the camera
            self.grabber = ic4.Grabber()
            self.grabber.device_open(self.dev_info)
        except Exception as e:
            self.error.emit(f"Could not open camera: {e}", "OPEN_ERR")
            return

        # (2) Build a QueueSinkListener in Python that will push each new frame
        class _Listener(ic4.QueueSinkListener):
            def __init__(self, qt_thread: "GrabberThread"):
                super().__init__()
                self.qt_thread = qt_thread

            def sink_connected(self, sink, image_type, min_buffers_required) -> bool:
                # We accept whatever buffers IC4 wants to give us.
                return True

            def frames_queued(self, sink: ic4.QueueSink):
                # Called by IC4 whenever a frame is available.
                try:
                    buf = sink.pop_output_buffer()
                except Exception as pop_err:
                    # maybe device disconnected
                    self.qt_thread.error.emit(f"Grab error: {pop_err}", "GRAB_ERR")
                    self.qt_thread._running = False
                    return

                # Convert the ImageBuffer → a NumPy array (in-place):
                #    * buf.width, buf.height, buf.stride  are available
                #    * buf.numpy_wrap() gives a H×W×4 BGRA uint8 view
                arr = buf.numpy_wrap()  # shape = (height, width, 4), BGRA

                # Example processing: blur + draw text over it
                cv2.blur(arr, (31, 31), arr)
                cv2.putText(
                    arr,
                    "Blurry Live Feed",
                    (50, 50),
                    fontFace=cv2.FONT_HERSHEY_SIMPLEX,
                    fontScale=1.0,
                    color=(0, 0, 255),      # red text in BGR
                    thickness=2,
                )

                # Convert BGRA → QImage.  We assume BGRA8888 layout:
                h, w, stride = buf.height, buf.width, buf.stride
                qimg = QImage(
                    arr.data,
                    w,
                    h,
                    stride,
                    QImage.Format.Format_BGRA8888
                ).rgbSwapped()  # to get correct R↔B ordering

                # Emit the QImage to the main GUI thread
                self.qt_thread.frame_ready.emit(qimg.copy())

                # Done with this buffer: let IC4 know we’re done
                buf.queue_buffer()

        listener = _Listener(self)

        # Create a QueueSink that requests BGRA8 buffers:
        self.queue_sink = ic4.QueueSink(listener, [ic4.PixelFormat.BGRA8], max_output_buffers=2)

        # Hook the sink into the grabber
        try:
            self.grabber.stream_setup(self.queue_sink)
        except Exception as e:
            self.error.emit(f"Could not start streaming: {e}", "STREAM_ERR")
            return

        # (3) Enter our “running” loop:  we actually don’t have to call grab() or snap();
        #     as soon as stream_setup(...) is called, IC4 will push frames into our sink/listener.
        self._running = True
        while self._running:
            # Just sleep; the listener is getting called in the background.
            time.sleep(0.01)

        # (4) Clean up on exit
        try:
            self.grabber.stream_stop()
            self.grabber.device_close()
        except:
            pass

    def stop(self):
        """Tell the thread to exit its loop."""
        self._running = False
        self.wait(2000)


#
# 2) MainWindow: a simple QWidget that contains one QLabel.
#    We will connect GrabberThread.frame_ready → update_label().
#
class MainWindow(QWidget):
    def __init__(self, grabber_thread: GrabberThread):
        super().__init__()
        self.grabber_thread = grabber_thread

        self.setWindowTitle("IC4 PyQt Live Demo")
        self.setFixedSize(QSize(800, 600))
        self.setLayout(QVBoxLayout())

        # One QLabel to show our incoming frames:
        self.video_label = QLabel("Starting camera...", self)
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("background-color: black; color: white;")
        self.layout().addWidget(self.video_label)

        # Hook signals:
        self.grabber_thread.frame_ready.connect(self.update_label)
        self.grabber_thread.error.connect(self.on_error)

        # Start the grabbing thread now that everything is connected:
        self.grabber_thread.start()

    @pyqtSlot(QImage)
    def update_label(self, img: QImage):
        """Convert QImage → QPixmap and display it in the QLabel."""
        pix = QPixmap.fromImage(img)
        self.video_label.setPixmap(pix.scaled(
            self.video_label.size(),
            Qt.KeepAspectRatio,
            Qt.FastTransformation
        ))

    @pyqtSlot(str, str)
    def on_error(self, msg: str, code: str):
        """Show any unexpected error in the QLabel (and stop streaming)."""
        self.video_label.setText(f"Error ({code}): {msg}")
        self.grabber_thread.stop()

    def closeEvent(self, event):
        """When the window closes, cleanly stop the grabber thread."""
        if self.grabber_thread.isRunning():
            self.grabber_thread.stop()
        super().closeEvent(event)


#
# 3) This is the script entry point.
#    We do:
#      (a) ic4.Library.init(…)
#      (b) Let user pick a camera index (text prompt).
#      (c) Create GrabberThread + MainWindow, then QApplication.exec().
#      (d) On exit, call ic4.Library.exit().
#
def main():
    # (a) Initialize IC4 once at startup
    ic4.Library.init(api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR)

    # (b) Let user pick a device from the console
    devs = ic4.DeviceEnum.devices()
    if not devs:
        print("No IC4 devices found. Exiting.")
        ic4.Library.exit()
        return

    print("Available devices:")
    for i, d in enumerate(devs):
        print(f"  [{i}]  {d.model_name}  (S/N: {d.serial})  [{d.interface.display_name}]")
    idx = int(input(f"Select index [0..{len(devs)-1}]: "))
    dev_info = devs[idx]

    # (c) Build the thread + window
    grab_thread = GrabberThread(dev_info)
    app = QApplication(sys.argv)
    win = MainWindow(grab_thread)
    win.show()
    app.exec()

    # (d) Clean up IC4 on exit
    ic4.Library.exit()


if __name__ == "__main__":
    main()