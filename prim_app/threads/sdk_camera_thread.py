# File: threads/sdk_camera_thread.py

import time
import numpy as np
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

class SDKCameraThread(QThread):
    """
    QThread that opens a chosen IC4 device, sets resolution (if requested),
    then streams frames via a QueueSink. Emits:
      - frame_ready(QImage, numpy.ndarray) each time a new frame is available
      - error(str, str) on any error
    """

    # (Optional) if you need to know exactly when the grabber is open:
    grabber_ready = pyqtSignal()

    # Emit each frame as a QImage and the raw BGRA NumPy array
    frame_ready = pyqtSignal(QImage, object)

    # On error: (message, error_code)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self.grabber = None
        self.device_info_to_open = None
        self.resolution_to_use = None

    def set_device_info(self, dev_info):
        """Called from the main thread before start()."""
        self.device_info_to_open = dev_info

    def set_resolution(self, resolution_tuple):
        """
        resolution_tuple == (width:int, height:int, pixel_format_name:str).
        Called from the main thread before start().
        """
        self.resolution_to_use = resolution_tuple

    def run(self):
        """
        (1) Create Grabber
        (2) device_open(dev_info)
        (3) Apply “AcquisitionMode=Continuous” + selected PixelFormat/Width/Height
        (4) stream_setup(QueueSink(listener=None, [chosen PF], max_output_buffers))
        (5) loop: pop_output_buffer(), wrap in QImage, emit frame_ready
        (6) cleanup on exit
        """
        # ─── Step 1: Initialize our grabber ──────────────────────────────────────
        try:
            self.grabber = ic4.Grabber()
        except ic4.IC4Exception as e:
            self.error.emit(f"Failed to create Grabber: {e}", str(e.code))
            return

        # ─── Step 2: Open the chosen device ────────────────────────────────────
        if not self.device_info_to_open:
            self.error.emit("No camera selected", "NO_DEVICE")
            return

        try:
            # This opens the camera (blocking call). After this, 
            # grabber.device_property_map will be valid.
            self.grabber.device_open(self.device_info_to_open)
        except ic4.IC4Exception as e:
            self.error.emit(f"Failed to open camera: {e}", str(e.code))
            return

        # ─── Step 3: Configure AcquisitionMode + PixelFormat + Width/Height ────
        try:
            propmap = self.grabber.device_property_map

            # 3a) Force “Continuous” mode if it exists
            acq_node = propmap.find_enumeration("AcquisitionMode")
            if acq_node:
                if "Continuous" in [e.name for e in acq_node.entries]:
                    acq_node.value = "Continuous"
                else:
                    acq_node.value = acq_node.entries[0].name

            # 3b) If the user picked a resolution+pixel_format, apply it
            # resolution_to_use = (width:int, height:int, pixel_format_name:str)
            if self.resolution_to_use:
                w, h, pf_name = self.resolution_to_use

                # Set PixelFormat first
                pf_node = propmap.find_enumeration("PixelFormat")
                if pf_node:
                    pf_node.value = pf_name

                # Next set Width/Height (some cameras expect PF first, then dims)
                w_node = propmap.find_integer("Width")
                h_node = propmap.find_integer("Height")
                if w_node and h_node:
                    w_node.value = w
                    h_node.value = h

                # NOTE: Some cameras need a “WidthMax/HeightMax → Width/Height” pattern,
                # but in our repro DMKs, simply setting “Width” & “Height” works.

        except ic4.IC4Exception as e:
            self.error.emit(f"Failed to set format: {e}", str(e.code))
            try:
                self.grabber.device_close()
            except:
                pass
            return

        # ─── Step 4: Create a QueueSink and attach it ───────────────────────────
        try:
            # We want raw bytes in a “Mono8” or “RGB24” or “BGRA8” form.
            # Suppose we know our camera supports “Mono8” (as your probe script discovered).
            # If you need color, use “BGRa8” or “BGRA8” (note the lowercase “a” in WGRA8).
            chosen_pf = self.resolution_to_use[2] if self.resolution_to_use else "Mono8"

            # Build a simple sink with no custom listener: we’ll call `.pop_output_buffer()` manually.
            sink = ic4.QueueSink(
                # pass None for the listener so we won’t rely on callbacks;
                # instead we pull with pop_output_buffer().
                listener=None,

                # We want exactly that one PixelFormat; if “Mono8” is correct:
                # (Use ic4.PixelFormat.Mono8 or ic4.PixelFormat.__getattr__(chosen_pf).)
                pixel_formats=[getattr(ic4.PixelFormat, chosen_pf)],

                # We only need 2 or 3 buffers “in flight” to avoid backpressure:
                max_output_buffers=3,
            )

            # Finally, bind the sink (and implicitly start acquisition because of the default
            # StreamSetupOption.ACQUISITION_START)
            self.grabber.stream_setup(sink)

            # If you want to delay starting acquisition until after some other calls,
            # you could pass `setup_option=ic4.StreamSetupOption.NONE` and then call
            # `self.grabber.acquisition_start()`.  But the default is to start immediately.

        except ic4.IC4Exception as e:
            self.error.emit(f"Failed to set up stream: {e}", str(e.code))
            try:
                self.grabber.device_close()
            except:
                pass
            return

        # ─── Optional: notify anyone watching that the grabber is ready ─────────
        self.grabber_ready.emit()

        # ─── Step 5: Main loop – pull frames out of the QueueSink ────────────────
        self._running = True
        while self._running:
            try:
                buf = sink.pop_output_buffer()
                # pop_output_buffer() will block internally until a buffer is ready—or
                # raise IC4Exception(ErrorCode.NoData) if no frame is available.

            except ic4.IC4Exception as e:
                # If you get ErrorCode.NoData (9) here, it simply means “no frame right now”;
                # you can either ignore it or treat it as a timeout.  We’ll just continue.
                if e.code == ic4.ErrorCode.NoData:
                    continue
                else:
                    # Signal any other error and break out
                    self.error.emit(f"Stream error: {e}", str(e.code))
                    break

            # ─ Extract raw bytes from the ImageBuffer into a NumPy array ───────────
            try:
                width = buf.width        # width in pixels
                height = buf.height      # height in pixels
                stride = buf.stride      # bytes per row

                # Create a 1D view of the raw pointer
                raw_ptr = buf.get_buffer()             # a Python “bytes”-like object
                arr = np.frombuffer(raw_ptr, dtype=np.uint8, count=height * stride)
                arr = arr.reshape((height, stride))
                # If it is Mono8, arr is (H, W) already.  If BGRA8, do:
                # arr = arr[:, : (width * 4)].reshape((height, width, 4))
                if buf.pixel_format == ic4.PixelFormat.Mono8:
                    np_img = arr[:, :width].copy()
                    # Convert grayscale → QImage.Format_Grayscale8
                    qimg = QImage(np_img.data, width, height, width, QImage.Format_Grayscale8)

                    # If you want BGR→RGB, you’d do something like:
                    # np_color = arr[:, :width*3].reshape((height, width, 3))
                    # qimg = QImage(np_color.data, width, height, width*3, QImage.Format_RGB888)

                else:
                    # Suppose the buffer is BGRA8; reshape accordingly:
                    arr4 = arr[:, : (width * 4)].reshape((height, width, 4))
                    # QImage.Format_BGRA8888 expects an 4-byte BGRA buffer.
                    qimg = QImage(arr4.data, width, height, stride, QImage.Format.Format_BGRA8888)

                # Finally make sure Qt owns its own copy (or else the memory might vanish
                # when you release buf).  Then emit:
                self.frame_ready.emit(qimg.copy(), arr.copy())

            except Exception as conv_e:
                self.error.emit(f"Frame‐conversion failed: {conv_e}", "CONV_ERR")

            # ─ Throttle or sleep briefly if you want a max frame‐rate ≲ your monitor’s refresh ─
            time.sleep(0.005)

        # ─── Step 6: Cleanup on exit ─────────────────────────────────────────────
        try:
            # This will stop streaming and close the device
            self.grabber.device_close()
        except:
            pass

    def stop(self):
        """Tell the loop to exit; then wait() on the thread."""
        self._running = False
        self.wait()