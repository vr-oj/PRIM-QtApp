# File: threads/sdk_camera_thread.py

import time
import imagingcontrol4 as ic4
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage


class SDKCameraThread(QThread):
    """
    QThread that opens a chosen IC4 device, applies a chosen resolution/pixel format,
    emits `grabber_ready` once the camera is open, and then continuously grabs frames.
    Signals:
      - grabber_ready(): emitted after device_open() and optional resolution setup succeed
      - frame_ready(QImage, numpy.ndarray): emitted for each new frame
      - error(str, str): emitted on any error (message, error_code)
    """

    # Emitted as soon as device_open() and resolution setup succeed
    grabber_ready = pyqtSignal()

    # Emitted for each new frame: a QImage (for display) and the raw numpy array (BGRA)
    frame_ready = pyqtSignal(QImage, object)

    # Emitted on error: (message, code)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self.grabber = None

        # These will be set by MainWindow before thread.start()
        self.device_info_to_open = None          # ic4.DeviceInfo
        self.resolution_to_use = None            # (width, height, pixel_format_name)

    def set_device_info(self, dev_info: ic4.DeviceInfo):
        """
        Store which DeviceInfo should be opened when the thread starts.
        """
        self.device_info_to_open = dev_info

    def set_resolution(self, resolution_tuple):
        """
        Store which resolution/pixel format to use.
        `resolution_tuple` must be (width, height, pixel_format_name).
        """
        self.resolution_to_use = resolution_tuple

    def run(self):
        """
        Called when thread.start() is invoked. This does:

          1. Create a Grabber() and open exactly the DeviceInfo passed in.
          2. (Optionally) force “Continuous” AcquisitionMode.
          3. Apply the chosen PixelFormat, Width, and Height.
          4. Start a grab-loop: call image_buffer_get_next(), convert to QImage + numpy array,
             and emit frame_ready() until stop() is called.
          5. On exit, close the device.
        """

        # 1) Validate that MainWindow gave us a DeviceInfo
        if self.device_info_to_open is None:
            self.error.emit("No camera device was provided", "NO_DEVICE_INFO")
            return

        try:
            # Create a Grabber and open the chosen camera
            self.grabber = ic4.Grabber()
            self.grabber.device_open(self.device_info_to_open)

        except ic4.IC4Exception as e:
            self.error.emit(f"Failed to open camera: {e}", "OPEN_ERR")
            return
        except Exception as e:
            self.error.emit(f"Unexpected error opening camera: {e}", "OPEN_ERR")
            return

        # 2) Put the camera into Continuous mode (if that node exists)
        try:
            acq_node = self.grabber.device_property_map.find_enumeration("AcquisitionMode")
            if acq_node:
                all_names = [entry.name for entry in acq_node.entries]
                if "Continuous" in all_names:
                    acq_node.value = "Continuous"
                else:
                    # fall back to the first available entry
                    acq_node.value = all_names[0]
        except Exception:
            # ignore if the camera doesn’t support AcquisitionMode
            pass

        # 3) Apply chosen PixelFormat, Width, and Height, if provided
        if self.resolution_to_use is not None:
            width, height, pf_name = self.resolution_to_use

            # (a) Set PixelFormat
            try:
                pf_node = self.grabber.device_property_map.find_enumeration("PixelFormat")
                if pf_node:
                    pf_node.value = pf_name
            except Exception:
                # if PixelFormat node is missing or fails, skip quietly
                pass

            # (b) Set Width and Height
            try:
                w_node = self.grabber.device_property_map.find_integer("Width")
                h_node = self.grabber.device_property_map.find_integer("Height")
                if w_node and h_node:
                    w_node.value = width
                    h_node.value = height
            except Exception:
                # if Width/Height nodes are missing or fail, skip quietly
                pass

        # 4) At this point, the camera is opened and configured.
        #    Notify MainWindow that grabber is ready.
        self.grabber_ready.emit()

        # 5) Enter grab loop
        self._running = True
        while self._running:
            try:
                # Wait up to 1000 ms for the next frame
                frame = self.grabber.image_buffer_get_next(timeout=1000)
            except ic4.IC4Exception as e:
                # A timeout or device-lost occurred
                self.error.emit(f"Grab error: {e}", "GRAB_ERR")
                break
            except Exception as e:
                self.error.emit(f"Unexpected grab error: {e}", "GRAB_ERR")
                break

            # The returned `frame` is an `ic4.ImageBuffer`.
            # Extract raw BGRA bytes, then wrap in a NumPy array.
            try:
                raw_ptr = frame.get_buffer()   # pointer to raw bytes (uint8*)
                width = frame.width
                height = frame.height
                stride = frame.stride         # bytes per row

                # Build a 1-D uint8 view of the entire buffer
                buf = np.frombuffer(raw_ptr, dtype=np.uint8, count=height * stride)

                # Reshape into (height, stride), then slice to (height, width*4),
                # and finally reshape to (height, width, 4) to get BGRA.
                arr = buf.reshape((height, stride))
                arr = arr[:, : (width * 4)]
                arr = arr.reshape((height, width, 4))   # BGRA

                # Convert BGRA → QImage. PyQt5’s QImage.Format_BGRA8888 expects BGRA,
                # so we can feed it directly.
                image = QImage(
                    arr.data, width, height, stride, QImage.Format.Format_BGRA8888
                )
                # If your colors appear swapped, drop the `.rgbSwapped()` call below.
                # For most IC4-driven DMK sensors, BGRA8888 is correct:
                image = image.rgbSwapped()  # turn BGRA→RGBA for Qt display

                # Emit a copy of each, so modifications in the slot won’t overwrite our buffer
                self.frame_ready.emit(image.copy(), arr.copy())

            except Exception as e:
                self.error.emit(f"Frame processing error: {e}", "FRAME_ERR")
                break

            # Optional throttle: sleep 10 ms so CPU usage doesn’t spike
            time.sleep(0.01)

        # 6) Clean up: close camera
        try:
            self.grabber.device_close()
        except Exception:
            pass

    def stop(self):
        """
        Signal the thread to end the grab loop cleanly.
        After setting _running=False, we wait() to ensure `run()` finishes.
        """
        self._running = False
        self.wait()
