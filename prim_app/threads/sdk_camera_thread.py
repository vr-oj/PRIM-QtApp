# threads/sdk_camera_thread.py

import time
import threading
import imagingcontrol4 as ic4
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

class _SilentQueueListener(ic4.QueueSinkListener):
    """
    A QueueSink listener that does nothing but keep the most‐recent
    ImageBuffer in `self.last_buffer`.  We do not do any processing in the callback,
    just hand it off to the QThread grab loop.
    """
    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self.last_buffer = None

    def sink_connected(self, sink, image_type, min_buffers_required):
        # Return True if we accept the proposed image_type/min_buffers.
        # IC4 is telling us “the device wants to hand you X pixel format”; as long as
        # we return True, IC4 will allocate buffers for us. Here we just accept it.
        return True

    def frames_queued(self, sink):
        # Called by IC4 when a new buffer is ready.
        # Pop it immediately and stash it in `self.last_buffer`.
        try:
            buf = sink.pop_output_buffer()
        except ic4.IC4Exception:
            return
        with self._lock:
            # If the user never called .release() on the previous last_buffer, free it now:
            if self.last_buffer is not None:
                try:
                    self.last_buffer.release()
                except Exception:
                    pass
            # Store the newly arrived buffer:
            self.last_buffer = buf


class SDKCameraThread(QThread):
    grabber_ready = pyqtSignal()
    frame_ready   = pyqtSignal(QImage, object)
    error         = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self.grabber = None
        self.device_info_to_open = None
        self.resolution_to_use = None

    def set_device_info(self, dev_info):
        self.device_info_to_open = dev_info

    def set_resolution(self, resolution_tuple):
        # resolution_tuple = (width, height, pixelFormatName)
        self.resolution_to_use = resolution_tuple

    def run(self):
        # 1) Ensure Library.init is called (or ignore “already called”):
        try:
            ic4.Library.init()
        except RuntimeError as e:
            if "already called" not in str(e).lower():
                raise

        # 2) Open the chosen camera:
        self.grabber = ic4.Grabber()
        try:
            self.grabber.device_open(self.device_info_to_open)
        except ic4.IC4Exception as e:
            self.error.emit(f"Failed to open camera: {e}", str(e.code))
            return

        # 3) If the user picked a custom resolution, program it:
        if self.resolution_to_use is not None:
            w, h, pf_name = self.resolution_to_use
            prop_map = self.grabber.device_property_map

            # 3a) Change PixelFormat:
            try:
                pf_node = prop_map.find_enumeration("PixelFormat")
                if pf_node and (pf_name in [e.name for e in pf_node.entries]):
                    pf_node.value = pf_name
            except ic4.IC4Exception:
                pass

            # 3b) Change Width/Height:
            try:
                w_prop = prop_map.find_integer("Width")
                h_prop = prop_map.find_integer("Height")
                if w_prop and h_prop:
                    w_prop.value = w
                    h_prop.value = h
            except ic4.IC4Exception:
                pass

        # Tell MainWindow that the grabber is now open & configured:
        self.grabber_ready.emit()

        # 4) Create a “silent” listener + QueueSink, then call stream_setup():
        listener = _SilentQueueListener()
        try:
            sink = ic4.QueueSink(listener, [ic4.PixelFormat.Mono8], max_output_buffers=3)
        except TypeError as e:
            self.error.emit(f"QueueSink init failed: {e}", "SINK_INIT_ERR")
            return

        try:
            # DO NOT pass StreamSetupOption.ACQUISITION_START explicitly,
            # because by default stream_setup(…) does exactly that.
            self.grabber.stream_setup(sink)
        except ic4.IC4Exception as e:
            self.error.emit(f"Failed to start stream: {e}", str(e.code))
            return

        # 5) Enter the grab loop:
        self._running = True
        while self._running:
            buf = None
            with listener._lock:
                buf = listener.last_buffer

            if buf is not None:
                # Convert buf → numpy → QImage, then emit:
                try:
                    width = buf.width
                    height = buf.height
                    stride = buf.stride
                    raw_ptr = buf.get_buffer()  # pointer to BGRA bytes
                    arr = np.frombuffer(raw_ptr, dtype=np.uint8, count=height * stride)
                    arr = arr.reshape((height, stride))[:, : (width * 4)]
                    arr = arr.reshape((height, width, 4))  # BGRA

                    # Construct a QImage (BGRA8888) and swap to RGB if needed:
                    img = QImage(
                        arr.data, width, height, stride, 
                        QImage.Format.Format_BGRA8888
                    ).rgbSwapped()

                    # Emit a *copy* so PyQt owns its own QImage data:
                    self.frame_ready.emit(img.copy(), arr.copy())
                except Exception:
                    pass

                # Release the ImageBuffer so IC4 can reuse it:
                try:
                    buf.release()
                except Exception:
                    pass

                # Clear listener.last_buffer so we don’t re‐display the same frame:
                with listener._lock:
                    listener.last_buffer = None

            # Throttle the loop slightly so we don’t spin too hot:
            time.sleep(0.005)

        # 6) Clean up on exit:
        try:
            self.grabber.acquisition_stop()
        except Exception:
            pass
        try:
            self.grabber.stream_stop()
        except Exception:
            pass
        try:
            self.grabber.device_close()
        except Exception:
            pass

    def stop(self):
        self._running = False
        self.wait()