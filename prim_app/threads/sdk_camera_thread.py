# File: threads/sdk_camera_thread.py

import time
import numpy as np
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

class SDKCameraThread(QThread):
    """
    QThread that:
      1. Uses a single ic4.Grabber to open a device + set resolution.
      2. Establishes a QueueSink (no listener callbacks).
      3. Loops, popping ImageBuffers, converting to QImage, emitting them.
      4. Cleans up on stop().

    Signals:
      grabber_ready() → emitted just after stream_setup & acquisition_start().
      frame_ready(QImage, numpy.ndarray) → each new frame.
      error(str, str) → on errors.
    """

    grabber_ready = pyqtSignal()
    # QImage + raw NumPy array (BGRA or Mono) on each frame
    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._running = False
        self.grabber = None
        self.device_info_to_open = None
        self.resolution_to_use = None
        self._sink = None

    def set_device_info(self, dev_info):
        """Store which DeviceInfo to open when run() starts."""
        self.device_info_to_open = dev_info

    def set_resolution(self, resolution_tuple):
        """
        Store which resolution/pixel format to use.
        `resolution_tuple` = (width, height, pixel_format_name).
        """
        self.resolution_to_use = resolution_tuple

    def run(self):
        """
        1) Open the requested device.
        2) Set PixelFormat + ROI (Width/Height).
        3) Create a QueueSink with the chosen PixelFormat.
        4) Call stream_setup(...) + acquisition_start().
        5) Loop: pop_output_buffer(), convert to QImage, emit.
        6) On _running=False, stop acquisition & close device.
        """
        # 1) Create a Grabber and open the desired device
        try:
            self.grabber = ic4.Grabber()
            self.grabber.device_open(self.device_info_to_open)
        except ic4.IC4Exception as e:
            self.error.emit(f"Failed to open camera: {e}", str(e.code))
            return

        # 2) Configure PixelFormat + Width/Height
        try:
            prop_map = self.grabber.device_property_map

            # Set AcquisitionMode to "Continuous" if available
            acq_node = prop_map.find_enumeration("AcquisitionMode")
            if acq_node:
                names = [e.name for e in acq_node.entries]
                acq_node.value = "Continuous" if "Continuous" in names else names[0]

            # Set PixelFormat
            w, h, pf_name = self.resolution_to_use
            pf_node = prop_map.find_enumeration("PixelFormat")
            if pf_node:
                pf_node.value = pf_name

            # Now set Width/Height nodes
            w_prop = prop_map.find_integer("Width")
            h_prop = prop_map.find_integer("Height")
            if w_prop and h_prop:
                w_prop.value = w
                h_prop.value = h

        except ic4.IC4Exception as e:
            self.error.emit(f"Failed to configure camera: {e}", str(e.code))
            try:
                self.grabber.device_close()
            except:
                pass
            return

        # 3) Create a QueueSink (no listener, so pass None)
        try:
            # The grammar is: QueueSink(listener, [PixelFormat.*], max_output_buffers)
            # We want the same pf_name → look up the actual enum constant from ic4.PixelFormat
            # You already set pf_node.value to pf_name, so the grabber will output that pixel format.
            # But for safety, request the same PixelFormat via ic4.PixelFormat.<pf_name>.
            pixel_enum = getattr(ic4.PixelFormat, pf_name)
            self._sink = ic4.QueueSink(None, [pixel_enum], max_output_buffers=3)

            # 4) Establish streaming (this also does acquisition_start by default)
            self.grabber.stream_setup(self._sink,
                                      setup_option=ic4.StreamSetupOption.ACQUISITION_START)

            # At this point, acquisition is running. Signal “grabber_ready”.
            self.grabber_ready.emit()

        except ic4.IC4Exception as e:
            self.error.emit(f"Stream setup or acquisition_start failed: {e}", str(e.code))
            try:
                self.grabber.device_close()
            except:
                pass
            return

        # 5) Main loop: pop buffers, convert to QImage, emit
        self._running = True
        while self._running:
            try:
                buf = self._sink.pop_output_buffer()
            except ic4.IC4Exception as e:
                # If no data for a short time, or device lost, break
                self.error.emit(f"Grab error: {e}", str(e.code))
                break

            # Each buf is an ic4.ImageBuffer. Extract its data:
            # New API: buffer properties are buf.image_width and buf.image_height
            width = buf.image_width
            height = buf.image_height
            stride = buf.stride  # bytes per row

            # 5a) Wrap it in a NumPy array (dtype=uint8)
            ptr = buf.get_buffer()  # low‐level memoryview
            arr = np.frombuffer(ptr, dtype=np.uint8, count=height * stride)
            arr = arr.reshape((height, stride))
            # slice out the actual pixels: if PF is BGRA (4 bytes/pixel)
            # If Mono8, stride = width (1 byte/pixel)
            channels = stride // width
            arr = arr[:, : (width * channels)]
            arr = arr.reshape((height, width, channels))

            # 5b) Convert to QImage. If the PixelFormat was a Bayer or Mono, you may need a different QImage format.
            # For example, if channels==1 (Mono8), do Format_Grayscale8. If channels==3 (BGR8), do Format_BGR888.
            if channels == 1:
                # Mono8 → QImage.Format.Format_Grayscale8
                image = QImage(arr.data, width, height, width, QImage.Format.Format_Grayscale8)
            elif channels == 3:
                # BGR8 → Format_BGR888 (PyQt6+), but in PyQt5 you can use Format.Format_RGB888 + rgbSwapped():
                image = QImage(arr.data, width, height, stride, QImage.Format.Format_BGR888)
            elif channels == 4:
                # BGRA8 → Format_BGRA8888
                image = QImage(arr.data, width, height, stride, QImage.Format.Format_BGRA8888)
            else:
                # Fallback: interpret raw as grayscale
                image = QImage(arr.data, width, height, width * channels, QImage.Format.Format_Grayscale8)

            # Emit a *copy* for safety
            self.frame_ready.emit(image.copy(), arr.copy())

            # Recycle the buffer (ImageBuffer.release())
            buf.release()

            # Optional throttle
            time.sleep(0.005)

        # 6) Clean up
        try:
            if self.grabber.is_acquisition_active:
                self.grabber.acquisition_stop()
        except:
            pass
        try:
            if self.grabber.is_device_open:
                self.grabber.device_close()
        except:
            pass

    def stop(self):
        """Signal the loop to end; then wait for thread to finish."""
        self._running = False
        self.wait()