# File: threads/sdk_camera_thread.py
import time
import imagingcontrol4 as ic4
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QImage

class SDKCameraThread(QThread):
    """
    QThread that:
      1. Opens the requested IC4 device.
      2. Sets resolution and pixel format.
      3. Calls Grabber.acquisition_start().
      4. Loops in image_buffer_get_next() until stopped.
      5. Emits `frame_ready(QImage, np.ndarray)` for each new frame.
      6. Emits `grabber_ready()` once acquisition has started successfully.
      7. Emits `error(str, str)` on any IC4 exception.
    """

    # Emitted once the Grabber is fully opened and acquisition has begun
    grabber_ready = pyqtSignal()

    # Emitted for each new frame: (QImage_for_display, raw_numpy_array)
    frame_ready = pyqtSignal(QImage, object)

    # Emitted if any error occurs: (message, error_code)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grabber = None
        self._running = False
        self.device_info_to_open = None   # will be set by MainWindow
        self.resolution_to_use = None     # tuple (width, height, pixel_format_name)

    def set_device_info(self, dev_info: ic4.DeviceInfo):
        """
        Store which DeviceInfo to open when the thread starts.
        """
        self.device_info_to_open = dev_info

    def set_resolution(self, resolution_tuple):
        """
        Store which resolution/pixel format to use.
        resolution_tuple = (width:int, height:int, pixel_format_name:str)
        """
        self.resolution_to_use = resolution_tuple

    def run(self):
        """
        Called when thread.start() is invoked.
        This will:
          1. Open the camera.
          2. Set pixel‐format, width, height.
          3. Start acquisition.
          4. Loop and grab frames via image_buffer_get_next().
        """
        # 1) Sanity check: did MainWindow call set_device_info() and set_resolution()?
        if not self.device_info_to_open or not self.resolution_to_use:
            self.error.emit("Camera or resolution not configured", "CONFIG_ERR")
            return

        try:
            # Create and open the Grabber
            grab = ic4.Grabber()
            grab.device_open(self.device_info_to_open)

            # 2) Configure pixel format & ROI (Width/Height) before starting acquisition.
            #    resolution_to_use = (w, h, pf_name)
            w, h, pf_name = self.resolution_to_use

            # Find and set PixelFormat enumeration node
            pf_node = grab.device_property_map.find_enumeration("PixelFormat")
            if pf_node:
                pf_node.value = pf_name

            # Set the Width and Height integer nodes
            w_prop = grab.device_property_map.find_integer("Width")
            h_prop = grab.device_property_map.find_integer("Height")
            if w_prop and h_prop:
                w_prop.value = w
                h_prop.value = h

            # 3) Start acquisition
            grab.acquisition_start()

            # Keep a reference to the open grabber so main thread can hand it to the control panel
            self.grabber = grab

            # Notify MainWindow that grabber is open and streaming is active
            self.grabber_ready.emit()

            # 4) Enter grab‐loop
            self._running = True
            while self._running:
                try:
                    # Pull the next frame (blocking up to 1000 ms)
                    frame = grab.image_buffer_get_next(timeout=1000)
                except ic4.IC4Exception as e:
                    # Possibly timed out or device lost
                    self.error.emit(f"Grab error: {e}", str(e.code))
                    break

                # Retrieve raw pointer & metadata
                raw_ptr = frame.get_buffer()   # pointer to raw BGRA bytes
                width = frame.width
                height = frame.height
                stride = frame.stride         # bytes per row

                # Build a numpy array view on that pointer
                buf = np.frombuffer(raw_ptr, dtype=np.uint8, count=height * stride)
                buf = buf.reshape((height, stride))
                buf = buf[:, : (width * 4)]   # drop any padding
                arr = buf.reshape((height, width, 4))  # shape = (h, w, BGRA)

                # Convert BGRA → QImage.  We use Format_BGR32 (alias for BGRA8888) and swap to RGB so correct colors appear.
                # Note: If your PyQt5 version supports QImage.Format.Format_BGRA8888, use that (as below); if not, use Format.Format_RGB32 but reorder bytes.
                try:
                    qt_image = QImage(
                        arr.data, width, height, stride, QImage.Format.Format_BGRA8888
                    ).rgbSwapped()
                except:
                    # Fallback if BGRA8888 is not available
                    qt_image = QImage(
                        arr.data, width, height, stride, QImage.Format.Format_RGB32
                    )

                # 5) Emit this frame out
                self.frame_ready.emit(qt_image.copy(), arr.copy())

                # Throttle a tiny bit (optional)
                time.sleep(0.005)

            # 6) Clean up when loop ends or stop() called
            try:
                grab.acquisition_stop()
            except Exception:
                pass
            try:
                grab.device_close()
            except Exception:
                pass

        except ic4.IC4Exception as e:
            # Any failure to open, configure, or start acquisition
            self.error.emit(f"Failed to open camera: {e}", str(e.code))
            return

    def stop(self):
        """
        Signal the grab loop to end cleanly.  Wait for the thread to finish.
        """
        self._running = False
        self.wait()