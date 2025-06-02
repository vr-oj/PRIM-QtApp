# prim_app/threads/sdk_camera_thread.py

import logging
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    # ─── Signals ──────────────────────────────────────────────────
    # Emitted once the IC4 Grabber is opened & ready for property‐sliders
    grabber_ready = pyqtSignal()

    # Emitted each time a new frame is ready (carries a QImage + raw buffer)
    frame_ready = pyqtSignal(QImage, object)

    # Emitted on any camera error (message, code)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grabber = None
        self._device_info = None
        self._resolution = None
        self._stop_requested = False

    def set_device_info(self, dev_info):
        self._device_info = dev_info

    def set_resolution(self, resolution_tuple):
        # resolution_tuple = (width, height, pixel_format_name)
        self._resolution = resolution_tuple

    def run(self):
        """
        1) Open & configure the IC4 Grabber
        2) Create a QueueSink(self, …) so IC4 calls our callbacks
        3) Emit grabber_ready(), start streaming, loop until stop() is called
        4) Cleanly stop streaming and close device (no Library.exit() here)
        """

        # ─── Step 1: Open Grabber & configure camera ────────────────────
        try:
            # (a) Create Grabber & open the camera
            self.grabber = ic4.Grabber()
            self.grabber.device_open(self._device_info)

            # (b) Force Continuous acquisition mode if available
            acq_node = self.grabber.device_property_map.find_enumeration(
                "AcquisitionMode"
            )
            if acq_node:
                names = [e.name for e in acq_node.entries]
                acq_node.value = "Continuous" if "Continuous" in names else names[0]

            # (c) Apply the chosen resolution/pixel‐format
            w, h, pf_name = self._resolution
            pf_node = self.grabber.device_property_map.find_enumeration("PixelFormat")
            if pf_node:
                pf_node.value = pf_name

            w_node = self.grabber.device_property_map.find_integer("Width")
            h_node = self.grabber.device_property_map.find_integer("Height")
            if w_node and h_node:
                w_node.value = int(w)
                h_node.value = int(h)

        except Exception as e:
            log.error("Camera thread encountered an error during setup.", exc_info=e)
            self.error.emit(str(e), getattr(e, "code", ""))
            return

        # ─── Step 2: Build a QueueSink that uses this thread as the listener ─────
        try:
            sink = ic4.QueueSink(
                self,  # `self` implements sink_connected() & frames_queued()
                [ic4.PixelFormat.BGR8],  # request BGR8
                max_output_buffers=1,
            )
            self.grabber.stream_setup(sink)
        except Exception as e:
            log.error(
                "Camera thread encountered an error setting up the sink.", exc_info=e
            )
            self.error.emit(str(e), getattr(e, "code", ""))
            return

        # ─── Step 3: Notify UI that grabber is ready, then start streaming ────
        self.grabber_ready.emit()
        try:
            self.grabber.stream_start()
        except Exception as e:
            log.error("Camera thread failed to start streaming.", exc_info=e)
            self.error.emit(str(e), getattr(e, "code", ""))
            return

        # ─── Step 4: Main loop—sleep briefly, letting IC4 call frames_queued() ──
        self._stop_requested = False
        while not self._stop_requested:
            self.msleep(10)

        # ─── Step 5: Clean up on stop request ───────────────────────────────
        try:
            self.grabber.stream_stop()
            self.grabber.device_close()
        except Exception:
            pass

        # **DO NOT** call ic4.Library.exit() here.  Your MainWindow.closeEvent()
        # will call Library.exit() exactly once.

    def stop(self):
        """Call this from the main thread to request the grab loop to exit."""
        self._stop_requested = True

    # ─── IC4 QueueSinkListener callbacks ───────────────────────────────────
    def sink_connected(
        self, sink: ic4.QueueSink, image_type: ic4.ImageType, min_buffers_required: int
    ) -> bool:
        """
        Called once, just before streaming begins.  Return True to accept the negotiated format.
        """
        return True

    def frames_queued(self, sink: ic4.QueueSink):
        """
        Called by IC4 every time a new buffer is available.  We pop it,
        wrap it in a NumPy array, convert to QImage, and emit frame_ready.
        """
        try:
            buf = sink.pop_output_buffer()
            arr = buf.numpy_wrap()  # shape = (height, width, 3) in BGR8

            h, w = arr.shape[:2]
            # QImage.Format_BGR888 is available in recent PyQt5/PyQt6. If you have an older Qt,
            # you may have to use Format_RGB888 and swap channels manually.
            qimg = QImage(arr.data, w, h, arr.strides[0], QImage.Format_BGR888)

            self.frame_ready.emit(qimg, buf)

        except Exception as e:
            log.error(f"Error popping buffer in frames_queued(): {e}", exc_info=e)
            self.error.emit(str(e), "")
