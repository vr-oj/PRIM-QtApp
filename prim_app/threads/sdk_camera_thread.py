# File: threads/sdk_camera_thread.py

import time
import imagingcontrol4 as ic4
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage


class SDKCameraThread(QThread):
    """
    QThread that opens a chosen IC4 DeviceInfo, applies a chosen resolution/pixel format,
    emits grabber_ready() once open, then continuously snaps frames via a SnapSink.
    Signals:
      - grabber_ready(): emitted after device_open() and optional resolution setup
      - frame_ready(QImage, numpy.ndarray): emitted for each new frame
      - error(str, str): emitted on any error (message, error_code)
    """

    # Emitted as soon as we have opened and configured the camera
    grabber_ready = pyqtSignal()

    # Emitted for each new frame: (QImage, numpy.ndarray)
    frame_ready = pyqtSignal(QImage, object)

    # Emitted when something goes wrong: (message, code)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self.grabber = None
        self.snap_sink = None

        # These will be set by MainWindow before thread.start()
        self.device_info_to_open = None   # ic4.DeviceInfo
        self.resolution_to_use = None     # (width:int, height:int, pixel_format_name:str)

    def set_device_info(self, dev_info: ic4.DeviceInfo):
        """Store which DeviceInfo to open when the thread runs."""
        self.device_info_to_open = dev_info

    def set_resolution(self, resolution_tuple):
        """
        Store which resolution/pixel format to use.
        `resolution_tuple` must be (width:int, height:int, pixel_format_name:str).
        """
        self.resolution_to_use = resolution_tuple

    def run(self):
        """
        Called when thread.start() is invoked. Steps:
          1.  Create a Grabber() and open exactly self.device_info_to_open.
          2.  (Optional) force Continuous AcquisitionMode.
          3.  Apply the chosen PixelFormat, Width, Height.
          4.  Create a SnapSink, start streaming → grab frames in a loop:
                frame = sink.snap(timeout)
              convert to BGRA numpy + QImage, emit frame_ready.
          5.  On stop(), break loop and close device.
        """
        # 1) Make sure MainWindow provided a DeviceInfo
        if self.device_info_to_open is None:
            self.error.emit("No camera device was provided", "NO_DEVICE_INFO")
            return

        try:
            self.grabber = ic4.Grabber()
            self.grabber.device_open(self.device_info_to_open)
        except ic4.IC4Exception as e:
            self.error.emit(f"Failed to open camera: {e}", "OPEN_ERR")
            return
        except Exception as e:
            self.error.emit(f"Unexpected error opening camera: {e}", "OPEN_ERR")
            return

        # 2) Put camera into Continuous mode if it exists
        try:
            acq_node = self.grabber.device_property_map.find_enumeration("AcquisitionMode")
            if acq_node:
                names = [entry.name for entry in acq_node.entries]
                acq_node.value = "Continuous" if "Continuous" in names else names[0]
        except Exception:
            # If that node is missing or fails, ignore
            pass

        # 3) Apply chosen PixelFormat, Width, Height
        if self.resolution_to_use is not None:
            width, height, pf_name = self.resolution_to_use

            # (a) Set PixelFormat
            try:
                pf_node = self.grabber.device_property_map.find_enumeration("PixelFormat")
                if pf_node:
                    pf_node.value = pf_name
            except Exception:
                pass

            # (b) Set Width & Height
            try:
                w_node = self.grabber.device_property_map.find_integer("Width")
                h_node = self.grabber.device_property_map.find_integer("Height")
                if w_node and h_node:
                    w_node.value = width
                    h_node.value = height
            except Exception:
                pass

        # 4) Create a SnapSink, hook it to the grabber, then emit grabber_ready()
        try:
            self.snap_sink = ic4.SnapSink()
            self.grabber.stream_setup(self.snap_sink)
        except ic4.IC4Exception as e:
            self.error.emit(f"Failed to set up SnapSink: {e}", "SINK_ERR")
            try:
                self.grabber.device_close()
            except Exception:
                pass
            return
        except Exception as e:
            self.error.emit(f"Unexpected error setting up SnapSink: {e}", "SINK_ERR")
            try:
                self.grabber.device_close()
            except Exception:
                pass
            return

        # Now the camera is warmed up & streaming. Notify UI:
        self.grabber_ready.emit()

        # 5) Enter grab loop
        self._running = True
        while self._running:
            try:
                # Snap one frame (timeout = 1000 ms)
                frame_buffer = self.snap_sink.snap(1000)
            except ic4.IC4Exception as e:
                self.error.emit(f"Grab error (snap failed): {e}", "GRAB_ERR")
                break
            except Exception as e:
                self.error.emit(f"Unexpected snap error: {e}", "GRAB_ERR")
                break

            # Convert the returned ImageBuffer → BGRA numpy array → QImage
            try:
                raw_ptr = frame_buffer.get_buffer()   # pointer to raw bytes
                w = frame_buffer.width
                h = frame_buffer.height
                stride = frame_buffer.stride     # bytes per row

                # Build a 1D uint8 view of the entire buffer
                buf = np.frombuffer(raw_ptr, dtype=np.uint8, count=h * stride)

                # Reshape into (h, stride), slice to (h, w*4), then reshape to (h, w, 4)
                arr = buf.reshape((h, stride))
                arr = arr[:, : (w * 4)]
                arr = arr.reshape((h, w, 4))   # BGRA

                # QImage needs RGBA, so we create a BGRA8888 and then rgbSwapped()
                img = QImage(arr.data, w, h, stride, QImage.Format.Format_BGRA8888)
                img = img.rgbSwapped()

                # Emit copies so downstream can modify them without stomping our buffer
                self.frame_ready.emit(img.copy(), arr.copy())
            except Exception as e:
                self.error.emit(f"Frame processing error: {e}", "FRAME_ERR")
                break

            # throttle a bit
            time.sleep(0.01)

        # 6) On exit: close device
        try:
            self.grabber.device_close()
        except Exception:
            pass

    def stop(self):
        """
        Signal the thread to end the grab loop. Then wait() until run() returns.
        """
        self._running = False
        self.wait()
