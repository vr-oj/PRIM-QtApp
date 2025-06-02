# File: threads/sdk_camera_thread.py

import time
import threading
import imagingcontrol4 as ic4
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage


class _SilentQueueListener(ic4.QueueSinkListener):
    """
    A QueueSink listener that just stores the latest ImageBuffer in .last_buffer.
    We do not process anything in the callback, we only pop the buffer,
    so that IC4 can continue streaming.  The main loop will fetch
    listener.last_buffer under lock.
    """
    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self.last_buffer = None

    def sink_connected(self, sink, image_type, min_buffers_required):
        # Accept whatever pixel‐format + min_buffers IC4 proposes
        return True

    def frames_queued(self, sink):
        # A new buffer is ready.  Pop it and stash it in last_buffer.
        try:
            buf = sink.pop_output_buffer()
        except ic4.IC4Exception:
            return

        with self._lock:
            # release the old buffer, if any
            if self.last_buffer is not None:
                try:
                    self.last_buffer.release()
                except Exception:
                    pass
            self.last_buffer = buf


class SDKCameraThread(QThread):
    """
    QThread that opens one IC4 camera, programs the requested resolution/pixel‐format,
    builds a QueueSink (silent listener), then continuously grabs whatever buffer
    is in listener.last_buffer, converts it → QImage, and emits frame_ready.
    """

    # Signal: grabber is open & ready (device_open + resolution set)
    grabber_ready = pyqtSignal()

    # Signal: new frame is available → (QImage, numpy‐ARGB‐array)
    frame_ready = pyqtSignal(QImage, object)

    # Signal: any IC4 error occurred → (message, error_code)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self.grabber = None
        self.device_info_to_open = None   # type: ic4.DeviceInfo
        self.resolution_to_use = None      # tuple (w, h, pixelFormatName)

    def set_device_info(self, dev_info):
        self.device_info_to_open = dev_info

    def set_resolution(self, resolution_tuple):
        # resolution_tuple == (width, height, pixel_format_name)
        self.resolution_to_use = resolution_tuple

    def run(self):
        # 1) Initialize IC4 library (ignore “already called”)
        try:
            ic4.Library.init()
        except RuntimeError as e:
            if "already called" not in str(e).lower():
                self.error.emit(f"Library.init() failed: {e}", "LIB_INIT_ERR")
                return

        # 2) Open the camera once:
        self.grabber = ic4.Grabber()
        try:
            self.grabber.device_open(self.device_info_to_open)
        except ic4.IC4Exception as e:
            self.error.emit(f"Failed to open camera: {e}", str(e.code))
            return

        # 3) If user chose a custom resolution, program PixelFormat/Width/Height now
        if self.resolution_to_use is not None:
            w, h, pf_name = self.resolution_to_use
            prop_map = self.grabber.device_property_map

            # 3a) Set PixelFormat
            try:
                pf_node = prop_map.find_enumeration("PixelFormat")
                if pf_node and (pf_name in [e.name for e in pf_node.entries]):
                    pf_node.value = pf_name
            except ic4.IC4Exception:
                pass

            # 3b) Set Width + Height
            try:
                w_prop = prop_map.find_integer("Width")
                h_prop = prop_map.find_integer("Height")
                if w_prop and h_prop:
                    w_prop.value = w
                    h_prop.value = h
            except ic4.IC4Exception:
                pass

        # 4) Notify MainWindow that the grabber is configured & open:
        self.grabber_ready.emit()

        # 5) Build a “silent” QueueSink + listener:
        listener = _SilentQueueListener()
        try:
            sink = ic4.QueueSink(listener, [ic4.PixelFormat.Mono8], max_output_buffers=3)
        except Exception as e:
            self.error.emit(f"QueueSink init failed: {e}", "SINK_INIT_ERR")
            # Make sure we close the device here:
            try:
                self.grabber.device_close()
            except Exception:
                pass
            return

        # 6) Start streaming (stream_setup() implicitly does acquisition_start()):
        try:
            self.grabber.stream_setup(sink)
        except ic4.IC4Exception as e:
            self.error.emit(f"Failed to start stream: {e}", str(e.code))
            try:
                self.grabber.device_close()
            except Exception:
                pass
            return

        # 7) Enter the grab loop:
        self._running = True
        while self._running:
            buf = None
            with listener._lock:
                buf = listener.last_buffer

            if buf is not None:
                # Convert Buf → np.array → QImage → emit:
                try:
                    width = buf.width
                    height = buf.height
                    stride = buf.stride
                    raw_ptr = buf.get_buffer()  # pointer to raw BGRA bytes
                    arr = np.frombuffer(raw_ptr, dtype=np.uint8, count=height * stride)
                    arr = arr.reshape((height, stride))[:, :(width * 4)]
                    arr = arr.reshape((height, width, 4))  # BGRA

                    # Build a QImage from BGRA8888 and then rgbSwapped to get RGB
                    qimg = QImage(arr.data, width, height, stride, QImage.Format.Format_BGRA8888)
                    qimg = qimg.rgbSwapped()

                    # Emit a copy so PyQt owns its own memory:
                    self.frame_ready.emit(qimg.copy(), arr.copy())
                except Exception:
                    pass

                # Release the buffer so IC4 can reuse it for the next frame:
                try:
                    buf.release()
                except Exception:
                    pass

                # Clear the listener’s last_buffer so we don’t display it again:
                with listener._lock:
                    listener.last_buffer = None

            # Throttle loop so CPU doesn’t spin too hot:
            time.sleep(0.005)

        # 8) Clean‐up on exit:
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