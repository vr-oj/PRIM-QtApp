# --- threads/sdk_camera_thread.py  (updated)  --------------------------

import time
import imagingcontrol4 as ic4
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui  import QImage

class Listener(ic4.QueueSinkListener):
    """
    A minimal listener that pops each new buffer, converts it to QImage, and emits a PyQt signal.
    """
    def __init__(self, qt_thread):
        super().__init__()
        self._thread = qt_thread  # reference to SDKCameraThread, so we can emit

    def sink_connected(self, sink: ic4.QueueSink, image_type: ic4.ImageType, min_buffers_required: int) -> bool:
        return True

    def frames_queued(self, sink: ic4.QueueSink):
        try:
            buf = sink.pop_output_buffer()         # get next ImageBuffer
        except ic4.IC4Exception as e:
            # NoData or other error → just ignore non-fatal
            return

        # Create a NumPy view (height × stride)
        arr = buf.numpy_wrap()

        # If your camera is mono8 or Bayer, convert to BGR8 in place (optional):
        #     cv2.cvtColor(arr, cv2.COLOR_BAYER_BG2BGR, arr)
        # For simplicity, assume arr is already BGR8 or BGRA8; pick correct Format

        h, w = buf.height, buf.width   # note: Buf now has .height / .width in v1.3.x
        stride = buf.stride

        # If the pixel format is, say, BGRa8 (BGRA), use Format_BGRA8888:
        #    qimg = QImage(arr.data, w, h, stride, QImage.Format.Format_BGRA8888)
        # If it's BGR8:
        qimg = QImage(arr.data, w, h, stride, QImage.Format.Format_BGR888)

        # Emit the QImage and raw array back to the Qt thread
        # (We copy here so the buffer can be released immediately.)
        self._thread.frame_ready.emit(qimg.copy(), arr.copy())

        # Release the buffer back to IC4 so it can be reused
        buf.release()


class SDKCameraThread(QThread):
    """
    QThread that:
      1) opens the requested IC4 device & resolution,
      2) sets up a QueueSink+Listener,
      3) emits `grabber_ready` once ready,
      4) runs until stop() is called, popping frames in a callback.
    """

    ### Signals to communicate back to your Qt UI:
    grabber_ready = pyqtSignal()
    frame_ready   = pyqtSignal(QImage, object)   # QImage + raw NumPy array (BGR/BGRA)
    error         = pyqtSignal(str, str)          # (message, code)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running          = False
        self.grabber           = None
        self.device_info_to_open = None
        self.resolution_to_use = None
        self._sink             = None
        self._listener         = None

    def set_device_info(self, dev_info):
        self.device_info_to_open = dev_info

    def set_resolution(self, resolution_tuple):
        # resolution_tuple = (width, height, pixel_format_name)
        self.resolution_to_use = resolution_tuple

    def run(self):
        # 1) Create a Grabber
        self.grabber = ic4.Grabber()
        try:
            # 2) Open the camera
            self.grabber.device_open(self.device_info_to_open)

            # 3) Set the desired pixel format & geometry
            w, h, pf_name = self.resolution_to_use

            # We must find the PixelFormat enumeration, set it, then set width/height
            pm = self.grabber.device_property_map
            pf_node = pm.find_enumeration("PixelFormat")
            if pf_node:
                pf_node.value = pf_name

            w_node = pm.find_integer("Width")
            h_node = pm.find_integer("Height")
            if w_node and h_node:
                w_node.value = w
                h_node.value = h

        except ic4.IC4Exception as e:
            self.error.emit(f"Failed to open camera: {e}", str(e.code))
            return

        # 4) Build a QueueSink + Listener
        try:
            # Pass None for listener first, we’ll replace below
            self._listener = Listener(self)
            # Pick the correct PixelFormat enum object from the string pf_name:
            pixel_fmt = getattr(ic4.PixelFormat, pf_name)

            self._sink = ic4.QueueSink(
                self._listener,
                [pixel_fmt],           # e.g. [ic4.PixelFormat.BGRa8] or [ic4.PixelFormat.Mono8]
                max_output_buffers=3
            )

            # 5) Start streaming immediately
            self.grabber.stream_setup(
                self._sink,
                setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )

        except ic4.IC4Exception as e:
            self.error.emit(f"Stream setup failed: {e}", str(e.code))
            try:
                self.grabber.device_close()
            except: pass
            return

        # 6) At this point, the sink/listener will start receiving frames automatically.
        self._running = True
        self.grabber_ready.emit()

        # 7) Just spin until _running == False. The actual pop happens in listener callback.
        while self._running and self.grabber.is_streaming:
            # Sleep briefly; the listener will fire its callback as soon as a frame arrives.
            time.sleep(0.01)

        # 8) On stop: tear down the stream & close the device
        try:
            if self.grabber.is_acquisition_active:
                self.grabber.acquisition_stop()
            if self.grabber.is_streaming:
                self.grabber.stream_stop()
            self.grabber.device_close()
        except Exception:
            pass

    def stop(self):
        self._running = False
        self.wait()