# prim_app/threads/sdk_camera_thread.py

import time
import imagingcontrol4 as ic4
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

class SDKCameraThread(QThread):
    """
    QThread that opens a chosen IC4 device, sets resolution (if requested),
    emits `grabber_ready` once the camera is open, then continuously grabs frames.
    Emits:
      - grabber_ready(): after device_open() and any resolution setup
      - frame_ready(QImage, numpy.ndarray): each time a new frame is available
      - error(str, str): on any error (message, error_code)
    """
    grabber_ready = pyqtSignal()
    frame_ready    = pyqtSignal(QImage, object)
    error          = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self.grabber = None
        self.device_info_to_open = None
        self.resolution_to_use = None

    def set_device_info(self, dev_info):
        """Store which DeviceInfo to open when the thread starts."""
        self.device_info_to_open = dev_info

    def set_resolution(self, resolution_tuple):
        """
        Store which resolution/pixel format to use.
        `resolution_tuple` should be (width, height, pixel_format_name).
        """
        self.resolution_to_use = resolution_tuple

    def run(self):
        """
        Called when thread.start() is invoked. We do:
          1. Open the device via ic4.Grabber
          2. (Optionally) set its width/height/pixel‐format
          3. Create a QueueSink and call stream_setup
          4. Start acquisition, then loop, popping buffers
        """

        # 1) Create Grabber and open the chosen device
        try:
            self.grabber = ic4.Grabber()
            self.grabber.device_open(self.device_info_to_open)
        except ic4.IC4Exception as e:
            self.error.emit(f"Failed to open camera: {e}", str(e.code))
            return

        # 2) If user requested a particular resolution/pixel‐format, set it now
        if self.resolution_to_use:
            (w, h, pf_name) = self.resolution_to_use
            try:
                pm = self.grabber.device_property_map

                # Set PixelFormat to the requested string (e.g. "Mono8" or "BGRa8")
                pf_node = pm.find_enumeration("PixelFormat")
                if pf_node:
                    pf_node.value = pf_name

                # Then set Width / Height
                w_prop = pm.find_integer("Width")
                h_prop = pm.find_integer("Height")
                if w_prop and h_prop:
                    w_prop.value = w
                    h_prop.value = h
            except ic4.IC4Exception as e:
                # If setting resolution fails, we still try to proceed,
                # but emit a warning so the user knows something went wrong.
                self.error.emit(f"Failed to set resolution/pixel format: {e}", str(e.code))
                # (We do NOT return here; we still try to stream.)

        # 3) At this point, create a QueueSink (polling style, listener=None).
        try:
            sink = ic4.QueueSink(
                None,                         # no callback listener
                [ic4.PixelFormat.Mono8],      # or [ic4.PixelFormat.BGRa8], etc.
                3                             # max_output_buffers
            )
        except TypeError as e:
            # In case the signature still differs, inform the user:
            self.error.emit(f"QueueSink init failed: {e}", "")
            # Clean up the open device before exiting:
            try:
                self.grabber.device_close()
            except:
                pass
            return

        # 4) Wire the sink into the grabber, then start acquisition
        try:
            self.grabber.stream_setup(sink)
            self.grabber.acquisition_start()
        except ic4.IC4Exception as e:
            self.error.emit(f"Stream setup or acquisition_start failed: {e}", str(e.code))
            try:
                self.grabber.device_close()
            except:
                pass
            return

        # Signal "grabber ready" so MainWindow can build controls
        self.grabber_ready.emit()

        # 5) Main loop: grab each image buffer from the sink
        self._running = True
        while self._running:
            try:
                buf = sink.pop_output_buffer()  # <-- no timeout arg, blocks until a buffer arrives
            except ic4.IC4Exception as e:
                # If no data or device lost, emit error and break the loop
                self.error.emit(f"Grab error: {e}", str(e.code))
                break

            # Convert ImageBuffer → NumPy array → QImage
            try:
                # 5a) Wrap buffer into numpy (BGRA8 is typical if your PixelFormat was BGRa8)
                array = buf.numpy_wrap()  # this gives us a (height, stride-by-bytes) array

                height = array.shape[0]
                stride = buf.stride             # bytes per row
                width = buf.width                # number of pixels
                # slice away any padding:
                arr2 = array[:, : (width * 4)]
                arr2 = arr2.reshape((height, width, 4))  # BGRA

                # Convert BGRA → QImage.  On most PyQt5 builds,
                # Format_BGR565 and Format_BGRA8888 both work; try BGRA8888:
                qimg = QImage(
                    arr2.data,
                    width,
                    height,
                    stride,
                    QImage.Format.Format_BGRA8888
                ).rgbSwapped()  # if necessary, remove .rgbSwapped() if colors are not reversed

                # 5b) Emit the new frame (copy() ensures thread-safety)
                self.frame_ready.emit(qimg.copy(), arr2.copy())

            except Exception as conv_e:
                # If conversion fails, at least release the buffer
                buf.release()
                self.error.emit(f"Buffer→QImage conversion failed: {conv_e}", "")
                break

            # 5c) Release the ImageBuffer so the sink can reuse it
            try:
                buf.release()
            except:
                pass

            # (Optional throttle—you can lower or remove this if you want maximum fps)
            time.sleep(0.01)

        # 6) Clean up: stop acquisition, close device, unref sink
        try:
            self.grabber.acquisition_stop()
        except:
            pass

        try:
            self.grabber.device_close()
        except:
            pass

        try:
            sink.__del__()  # forcibly unref the sink (it may complain if library was already exited)
        except:
            pass


    def stop(self):
        """Signal the thread to end the grab loop cleanly."""
        self._running = False
        self.wait()