# threads/sdk_camera_thread.py

import time
import numpy as np
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

class SDKCameraThread(QThread):
    grabber_ready = pyqtSignal()
    frame_ready   = pyqtSignal(QImage, object)
    error         = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running         = False
        self.grabber          = None
        self.device_info      = None   # type: ic4.DeviceInfo
        self.resolution_tuple = None   # (width, height, pixelFormatName)

    def set_device_info(self, dev_info):
        self.device_info = dev_info

    def set_resolution(self, res_tuple):
        # res_tuple = (width, height, pixelFormatName)
        self.resolution_tuple = res_tuple

    def run(self):
        # 1) The IC4 library was already initialized in prim_app.py → do NOT call Library.init() here.
        try:
            # 2) Create a Grabber and open the requested device
            self.grabber = ic4.Grabber()
            self.grabber.device_open(self.device_info)
        except ic4.IC4Exception as e:
            self.error.emit(f"Failed to open camera: {e}", str(e.code))
            return

        try:
            # 3) Apply the requested resolution/pixel format
            w, h, pf_name = self.resolution_tuple
            propmap = self.grabber.device_property_map

            # Set PixelFormat
            pf_node = propmap.find_enumeration("PixelFormat")
            pf_node.value = pf_name

            # Set Width/Height
            w_prop = propmap.find_integer("Width")
            h_prop = propmap.find_integer("Height")
            w_prop.value = w
            h_prop.value = h

            # Force “Continuous” mode if present
            acq_node = propmap.find_enumeration("AcquisitionMode")
            if acq_node and "Continuous" in [e.name for e in acq_node.entries]:
                acq_node.value = "Continuous"

        except ic4.IC4Exception as e:
            # Something went wrong while setting the resolution
            self.error.emit(f"Failed to configure resolution: {e}", str(e.code))
            try:
                self.grabber.device_close()
            except:
                pass
            return

        try:
            # 4) Create a QueueSink that will hand us raw buffers
            #    Notice: listener=None, correct pixel‐formats argument form
            sink = ic4.QueueSink(
                None,                                 # we don’t need a callback listener
                [ic4.PixelFormat.BGRa8],              # or Mono8 / BGR8, whichever you prefer
                max_output_buffers=3
            )

            # 5) Hook up the stream (this will *also* start acquisition for us)
            self.grabber.stream_setup(sink)
        except ic4.IC4Exception as e:
            self.error.emit(f"Stream setup failed: {e}", str(e.code))
            try:
                self.grabber.device_close()
            except:
                pass
            return

        # Now let the MainWindow know that we are “grabber‐ready”
        self.grabber_ready.emit()

        # 6) Enter the grab loop
        self._running = True
        while self._running:
            try:
                buf = sink.pop_output_buffer()  # no timeout= in 1.3.x
            except ic4.IC4Exception as e:
                # No frames available, or device lost, etc.
                self.error.emit(f"Grab error: {e}", str(e.code))
                break

            # Convert ImageBuffer → NumPy array → QImage
            arr = buf.numpy_wrap()  # gives you a H×W×4 BGRA buffer if you requested BGRa8
            height, width = arr.shape[:2]
            stride = arr.strides[0]

            # We have BGRA in “arr”, but QImage expects Format_BGRA8888
            qim = QImage(
                arr.data, width, height, stride, QImage.Format.Format_BGRA8888
            )

            # Emit a copy (so that IC4 can reuse the buffer internally)
            self.frame_ready.emit(qim.copy(), arr.copy())

            # Tell IC4 that we’re done with this buffer so it can be reused
            buf.release()

            time.sleep(0.005)

        # 7) When _running becomes False, clean up
        try:
            self.grabber.stream_stop()
            self.grabber.device_close()
        except:
            pass

    def stop(self):
        self._running = False
        self.wait()