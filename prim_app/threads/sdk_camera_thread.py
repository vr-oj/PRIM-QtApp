# prim_app/threads/sdk_camera_thread.py

import logging
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    # emitted when grabber is open & ready (so UI can build controls)
    grabber_ready = pyqtSignal()

    # emitted for each new frame: (QImage, raw_buffer_object)
    frame_ready = pyqtSignal(QImage, object)

    # emitted on error: (message, code)
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
        try:
            # 1) Initialize the library
            ic4.Library.init(
                api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR
            )

            # 2) Create grabber and open the device
            self.grabber = ic4.Grabber()
            self.grabber.device_open(self._device_info)

            # 3) Force “Continuous” mode if possible (same as before)
            acq_node = self.grabber.device_property_map.find_enumeration(
                "AcquisitionMode"
            )
            if acq_node:
                vals = [e.name for e in acq_node.entries]
                if "Continuous" in vals:
                    acq_node.value = "Continuous"
                else:
                    acq_node.value = vals[0]

            # 4) Set the chosen PixelFormat, Width, and Height
            w, h, pf = self._resolution
            pf_node = self.grabber.device_property_map.find_enumeration("PixelFormat")
            if pf_node:
                pf_node.value = pf

            w_node = self.grabber.device_property_map.find_integer("Width")
            h_node = self.grabber.device_property_map.find_integer("Height")
            if w_node and h_node:
                w_node.value = int(w)
                h_node.value = int(h)

            # 5) Build a QueueSink that hands you BGR8 buffers
            listener = self  # implement frames_queued in this class
            sink = ic4.QueueSink(listener, [ic4.PixelFormat.BGR8], max_output_buffers=1)
            self.grabber.stream_setup(sink)

            # 6) Emit “grabber_ready” so UI can build property‐sliders
            self.grabber_ready.emit()

            # 7) Start streaming
            self.grabber.stream_start()

            # 8) Busy‐loop until stop requested
            while not self._stop_requested:
                ic4.sleep(10)  # or QThread.msleep(10)

            # 9) On exit, stop streaming
            self.grabber.stream_stop()
            self.grabber.device_close()

        except Exception as e:
            log.exception("Camera thread encountered an error.")
            msg = str(e)
            code = getattr(e, "code", "")
            self.error.emit(msg, code)

        finally:
            try:
                ic4.Library.exit()
            except Exception:
                pass

    def stop(self):
        self._stop_requested = True

    # ← This is the callback from QueueSink when a new frame arrives
    def frames_queued(self, sink):
        try:
            buf = sink.pop_output_buffer()

            # Create a NumPy view
            arr = buf.numpy_wrap()  # shape = (height, width, channels)
            h, w = arr.shape[0], arr.shape[1]

            # Build a QImage from the raw BGR data
            # Note: Format_BGR888 is available in recent PyQt5; adjust if needed
            qimg = QImage(
                arr.data,
                w,
                h,
                arr.strides[0],
                QImage.Format_BGR888,
            )

            # Emit the frame to the UI
            self.frame_ready.emit(qimg, buf)

        except Exception as e:
            log.error(f"Error popping buffer: {e}")
            self.error.emit(str(e), "")

        finally:
            # In high‐fps scenarios, we don't re‐queue the buffer manually;
            # the IC4 sink reuses a single max_output_buffer=1 buffer.
            pass
