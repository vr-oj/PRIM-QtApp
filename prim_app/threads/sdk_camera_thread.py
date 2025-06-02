import time
import imagingcontrol4 as ic4
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

class _SilentQueueListener(ic4.QueueSinkListener):
    """
    A minimal listener for QueueSink that just pops each frame.
    """
    def __init__(self):
        super().__init__()
        self.last_buffer = None

    def sink_connected(self, sink: ic4.QueueSink, image_type: ic4.ImageType, min_buffers_required: int) -> bool:
        # Tell the sink we’re OK to receive whatever image_type it chooses
        return True

    def frames_queued(self, sink: ic4.QueueSink):
        try:
            buf = sink.pop_output_buffer()
            # Store or immediately release. Here we just keep a reference so it doesn't free.
            self.last_buffer = buf
        except ic4.IC4Exception:
            pass


class SDKCameraThread(QThread):
    grabber_ready = pyqtSignal()
    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self.grabber: ic4.Grabber = None
        self.device_info_to_open = None
        self.resolution_to_use = None

    def set_device_info(self, dev_info):
        self.device_info_to_open = dev_info

    def set_resolution(self, resolution_tuple):
        self.resolution_to_use = resolution_tuple

    def run(self):
        # 1) Initialize IC4 library (if not already done)
        try:
            ic4.Library.init()
        except ic4.IC4Exception as e:
            # If already initialized, ignore
            if e.code != ic4.ErrorCode.LibraryNotInitialized and "already called" not in str(e).lower():
                self.error.emit(f"IC4 init failed: {e}", str(e.code))
                return

        # 2) Create Grabber and open device
        self.grabber = ic4.Grabber()
        try:
            self.grabber.device_open(self.device_info_to_open)
        except ic4.IC4Exception as e:
            self.error.emit(f"Failed to open camera: {e}", str(e.code))
            return

        # 3) If user requested a specific resolution/pixelformat, program it now:
        if self.resolution_to_use is not None:
            w, h, pf_name = self.resolution_to_use
            prop_map = self.grabber.device_property_map
            # Write PixelFormat
            pf_node = prop_map.find_enumeration("PixelFormat")
            if pf_node and pf_name in [entry.name for entry in pf_node.entries]:
                try:
                    pf_node.value = pf_name
                except ic4.IC4Exception:
                    pass
            # Write Width & Height
            w_prop = prop_map.find_integer("Width")
            h_prop = prop_map.find_integer("Height")
            if w_prop and h_prop:
                try:
                    w_prop.value = w
                    h_prop.value = h
                except ic4.IC4Exception:
                    pass

        # 4) Signal to MainWindow that the grabber is open:
        self.grabber_ready.emit()

        # 5) Set up a streaming sink with a silent listener
        listener = _SilentQueueListener()
        # Pick one or more pixel formats your camera supports. Mono8 is a reasonable default:
        formats = [ic4.PixelFormat.Mono8]
        try:
            sink = ic4.QueueSink(listener, formats, max_output_buffers=3)
        except TypeError as e:
            self.error.emit(f"QueueSink init failed: {e}", "SINK_INIT_ERR")
            return

        try:
            self.grabber.stream_setup(sink)
        except ic4.IC4Exception as e:
            self.error.emit(f"Failed to start stream: {e}", str(e.code))
            return

        # 6) Start acquisition
        try:
            self.grabber.acquisition_start()
        except ic4.IC4Exception as e:
            self.error.emit(f"Acquisition start failed: {e}", str(e.code))
            return

        self._running = True
        while self._running:
            # As soon as a buffer is queued, listener.frames_queued() will have popped it
            # from the sink and made it available as listener.last_buffer.
            buf = listener.last_buffer
            if buf is not None:
                # Convert ic4.ImageBuffer → numpy → QImage
                try:
                    width = buf.width
                    height = buf.height
                    stride = buf.stride
                    raw_ptr = buf.get_buffer()
                    arr = np.frombuffer(raw_ptr, dtype=np.uint8, count=(height * stride))
                    arr = arr.reshape((height, stride))[:, : (width * 4)]
                    arr = arr.reshape((height, width, 4))  # BGRA

                    # Convert BGRA → QImage:
                    img = QImage(
                        arr.data, width, height, stride, QImage.Format.Format_BGRA8888
                    ).rgbSwapped()

                    self.frame_ready.emit(img.copy(), arr.copy())
                except Exception:
                    pass

                # Release the buffer so the sink can reuse it
                try:
                    buf.release()
                except Exception:
                    pass

                # Clear listener.last_buffer so we don’t re‐send the same one
                listener.last_buffer = None

            # A small sleep to avoid 100% CPU usage
            time.sleep(0.005)

        # 7) Clean up: stop acquisition, stop stream, close device
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