# File: threads/sdk_camera_thread.py
import time
import imagingcontrol4 as ic4
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QImage


class SDKCameraThread(QThread):
    """
    A QThread that initializes IC4, opens the first DMK device found,
    and continuously grabs frames. Emits each frame as a QImage + raw numpy array.
    """

    # Emitted each time a new frame is available:
    #   - QImage (for direct display)
    #   - numpy.ndarray (raw BGRA data, if you need further processing)
    frame_ready = pyqtSignal(QImage, object)

    # Emitted on error (message, error_code)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self.grabber = None

    def run(self):
        """
        Called when thread.start() is invoked. We do:
          1. Initialize IC4 library
          2. Enumerate and open the first available DMK device
          3. Set up grabbing in a loop until self._running is False
        """

        try:
            # 1) Initialize IC4
            ic4.Library.init()  # or: with ic4.Library.init_context(): …
        except ic4.IC4Exception as e:
            self.error.emit(f"Failed to init IC4: {e}", "IC4_INIT_ERROR")
            return

        # 2) Create a Grabber and open the first device
        self.grabber = ic4.Grabber()
        devices = self.grabber.device_info.enumerate()
        if not devices:
            self.error.emit("No IC4 camera found", "NO_DEVICE")
            return

        # Just pick the first DMK device
        dev_info = devices[0]
        try:
            self.grabber.device_info = dev_info
            self.grabber.device_open()  # open the camera
        except ic4.IC4Exception as e:
            self.error.emit(f"Failed to open camera: {e}", "OPEN_ERR")
            return

        # 3) Start streaming (grab) frames
        #    Note: By default, Grabber.grab() returns a pointer to a frame object.
        #    We'll convert that into BGRA bytes → QImage.
        self._running = True
        while self._running:
            try:
                frame = self.grabber.image_buffer_get_next(
                    timeout=1000
                )  # wait up to 1s
            except ic4.IC4Exception as e:
                # timed out or device lost
                self.error.emit(f"Grab error: {e}", "GRAB_ERR")
                break

            # The frame is an imagingcontrol4.ImageBuffer object. Extract raw data.
            # We’ll assume the pixel format is BGRA8; adjust if needed.
            raw_ptr = frame.get_buffer()  # pointer to raw bytes
            width = frame.width
            height = frame.height
            stride = frame.stride  # bytes per row

            # Create a NumPy array view onto that buffer (dtype=uint8)
            buf = np.frombuffer(raw_ptr, dtype=np.uint8, count=height * stride)
            # Reshape into (height, stride) then slice to (height, width, 4)
            arr = buf.reshape((height, stride))
            arr = arr[:, : (width * 4)]  # cut off any padding
            arr = arr.reshape((height, width, 4))  # BGRA

            # Convert BGRA → QImage (Qt expects RGBA or BGRA depending on format)
            # Note: QImage.Format.Format_BGR30 etc. but we can use Format.Format_ARGB32_Premultiplied
            # or Format.Format_BGRA8888 (depending on your PyQt5 version). Try BGRA8888 first:
            image = QImage(
                arr.data, width, height, stride, QImage.Format.Format_BGRA8888
            ).rgbSwapped()  # if colors come out reversed, drop the rgbSwapped()

            # Emit the QImage and raw array
            self.frame_ready.emit(image.copy(), arr.copy())

            # Throttle if needed (optional)
            time.sleep(0.01)

        # Clean up on exit
        try:
            self.grabber.device_close()
        except Exception:
            pass
        try:
            ic4.Library.close()  # release IC4
        except Exception:
            pass

    def stop(self):
        """Signal the thread to end the grab loop cleanly."""
        self._running = False
        self.wait()
