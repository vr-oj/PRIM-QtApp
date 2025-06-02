# ─── prim_app/threads/sdk_camera_thread.py ─────────────────────────────────

import logging
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    # Emitted once the grabber is opened and streaming has started
    grabber_ready = pyqtSignal()

    # Emitted for each new frame: (QImage, raw_buffer_object)
    frame_ready = pyqtSignal(QImage, object)

    # Emitted on error: (message, code)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grabber = None
        self._device_info = None
        self._resolution = None  # (w, h, pixel_format_name)
        self._stop_requested = False

    def set_device_info(self, dev_info):
        self._device_info = dev_info

    def set_resolution(self, resolution_tuple):
        # resolution_tuple == (width, height, pixel_format_name)
        self._resolution = resolution_tuple

    def run(self):
        try:
            # ─── 1) Initialize the IC4 library here ─────────────────────────────
            ic4.Library.init(
                api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR
            )

            # ─── 2) Create a Grabber and open the chosen device ────────────────
            self.grabber = ic4.Grabber()
            self.grabber.device_open(self._device_info)

            # ─── 3) Force Continuous acquisition mode if available ─────────────
            acq_node = self.grabber.device_property_map.find_enumeration(
                "AcquisitionMode"
            )
            if acq_node:
                names = [e.name for e in acq_node.entries]
                if "Continuous" in names:
                    acq_node.value = "Continuous"
                else:
                    acq_node.value = names[0]  # pick the first fallback

            # ─── 4) Set PixelFormat, Width, and Height ─────────────────────────
            w, h, pf = self._resolution
            pf_node = self.grabber.device_property_map.find_enumeration("PixelFormat")
            if pf_node:
                pf_node.value = pf

            w_node = self.grabber.device_property_map.find_integer("Width")
            h_node = self.grabber.device_property_map.find_integer("Height")
            if w_node and h_node:
                w_node.value = int(w)
                h_node.value = int(h)

            # ─── 5) Build a QueueSink for BGR8, then start acquisition in one call ─
            # "listener" is this QThread because we implement frames_queued(...) below.
            listener = self
            sink = ic4.QueueSink(listener, [ic4.PixelFormat.BGR8], max_output_buffers=1)

            # Use StreamSetupOption.ACQUISITION_START so that stream_setup both configures
            # the sink _and_ starts grabbing.  (No .stream_start() call needed.)
            self.grabber.stream_setup(sink, ic4.StreamSetupOption.ACQUISITION_START)

            # ─── 6) At this point, grabbing is already running; tell MainWindow to build controls ─
            self.grabber_ready.emit()

            # ─── 7) Busy‐loop here until stopped ────────────────────────────────
            while not self._stop_requested:
                # Note: IC4 Python provides its own sleep; you could also do QThread.msleep(10)
                ic4.sleep(10)

            # ─── 8) Stop the stream and close device ───────────────────────────
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

    # ─── This is the QueueSink callback; every time a new buffer arrives, this is called ─
    def frames_queued(self, sink):
        try:
            buf = sink.pop_output_buffer()
            arr = buf.numpy_wrap()  # NumPy view of shape (H,W,3), dtype=uint8
            h, w = arr.shape[0], arr.shape[1]

            # Build a QImage from the BGR data
            # (Note: Format_BGR888 is provided by PyQt5 >= 5.12. Adjust if needed.)
            qimg = QImage(arr.data, w, h, arr.strides[0], QImage.Format_BGR888)

            # Emit to the UI
            self.frame_ready.emit(qimg, buf)

        except Exception as ex:
            log.error(f"Error popping buffer: {ex}")
            self.error.emit(str(ex), "")

        finally:
            # We do not need to re‐queue; max_output_buffers=1 ensures IC4 recycles automatically.
            pass
