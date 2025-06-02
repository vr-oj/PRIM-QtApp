# prim_app/threads/sdk_camera_thread.py

import time
import ctypes
import imagingcontrol4 as ic4
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

class SDKCameraThread(QThread):
    """
    QThread that opens a chosen IC4 device, sets resolution (if requested),
    establishes a QueueSink, then continuously pops frames and emits them.
    Emits:
      - grabber_ready(): once camera is open and streaming
      - frame_ready(QImage, numpy.ndarray): each new frame
      - error(str, str): on any error (message, error_code)
    """

    # Signal emitted as soon as the stream has started successfully
    grabber_ready = pyqtSignal()

    # Signal emitted for each new frame: QImage (for display) and raw NumPy array (BGRA or GRAY)
    frame_ready = pyqtSignal(QImage, object)

    # Signal for errors: (message, error_code)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self.grabber = None
        self.device_info_to_open = None
        self.resolution_to_use = None
        self.queue_sink = None

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
        Called when thread.start() is invoked. Steps:
          1) Create Grabber and open chosen device.
          2) Set pixel format & resolution if requested.
          3) Create a silent QueueSink and call stream_setup().
          4) Emit grabber_ready(), then loop popping buffers and emitting frame_ready().
        """
        # 1) Create a Grabber and open the chosen device
        try:
            self.grabber = ic4.Grabber()
            if self.device_info_to_open is None:
                raise RuntimeError("No DeviceInfo specified")
            self.grabber.device_open(self.device_info_to_open)
        except Exception as e:
            self.error.emit(f"Failed to open camera: {e}", str(getattr(e, "code", "")))
            return

        # 2) If the user requested a particular (w, h, pixelFormatName), set it now
        if self.resolution_to_use is not None:
            try:
                w, h, pf_name = self.resolution_to_use
                prop_map = self.grabber.device_property_map

                # 2a) Set PixelFormat to the chosen name
                pf_node = prop_map.find_enumeration("PixelFormat")
                if pf_node and pf_name in [e.name for e in pf_node.entries]:
                    pf_node.value = pf_name

                # 2b) Now set Width/Height
                w_node = prop_map.find_integer("Width")
                h_node = prop_map.find_integer("Height")
                if w_node:
                    w_node.value = w
                if h_node:
                    h_node.value = h

                # 2c) (Optional) force continuous mode
                acq_node = prop_map.find_enumeration("AcquisitionMode")
                if acq_node and "Continuous" in [e.name for e in acq_node.entries]:
                    acq_node.value = "Continuous"
            except Exception as e:
                # If something goes wrong here, bail out
                self.error.emit(f"Failed to set resolution: {e}", str(getattr(e, "code", "")))
                try:
                    self.grabber.device_close()
                except:
                    pass
                return

        # 3) Create a silent QueueSink → pass None as listener (we’ll poll manually)
        try:
            # The “formats” list must match one of the camera’s available pixel formats.
            # If you want grayscale (Mono8), change to PixelFormat.Mono8. Here we pick BGRA8 first.
            # (Mono8 cameras often also can output “BGRa8” or similar; use whichever works for you.)
            desired_formats = [ic4.PixelFormat.BGRa8, ic4.PixelFormat.Mono8]
            self.queue_sink = ic4.QueueSink(
                None,                         # no callback/listener
                formats=desired_formats,      # ask IC4 to hand us either BGRA8 or Mono8
                max_output_buffers=2
            )

            # 3b) Establish the data stream → this also starts acquisition by default
            self.grabber.stream_setup(self.queue_sink)

        except ic4.IC4Exception as e:
            self.error.emit(f"Failed to set up streaming: {e}", str(e.code))
            try:
                self.grabber.device_close()
            except:
                pass
            return
        except Exception as e:
            self.error.emit(f"Unexpected error in stream_setup: {e}", "")
            try:
                self.grabber.device_close()
            except:
                pass
            return

        # 4) We’re now streaming. Emit grabber_ready so MainWindow can enable sliders, etc.
        self.grabber_ready.emit()

        # 5) Enter main grab loop
        self._running = True
        while self._running:
            try:
                # pop_output_buffer() will block until a buffer is available
                buf = self.queue_sink.pop_output_buffer()
            except ic4.IC4Exception as e:
                # NoData or device lost → “NoData” code is 9. Other codes may mean disconnect.
                self.error.emit(f"Grab error: {e}", str(e.code))
                break
            except Exception as e:
                self.error.emit(f"Unexpected pop error: {e}", "")
                break

            # The returned buf is an ImageBuffer. We can query:
            #   buf.width, buf.height, buf.stride, buf.get_buffer()
            try:
                width = buf.width
                height = buf.height
                stride = buf.stride

                # 1D view of all bytes:
                raw_ptr = buf.get_buffer()
                arr = np.frombuffer(raw_ptr, dtype=np.uint8, count=height * stride)
                arr = arr.reshape((height, stride))
                arr = arr[:, : (width * 4)]      # if BGRA, 4 bytes per pixel
                arr = arr.reshape((height, width, 4))

                # Convert to QImage (BGRA8888).  If your camera is mono, you could do a 1‐channel
                # conversion instead (e.g. use QImage.Format_Grayscale8).
                image = QImage(
                    arr.data,
                    width,
                    height,
                    stride,
                    QImage.Format.Format_BGRA8888
                )

                # Emit a copy (so IC4 buffer can get released)
                self.frame_ready.emit(image.copy(), arr.copy())

            except Exception as e:
                # If something fails converting → still release and continue
                self.error.emit(f"Frame‐processing error: {e}", "")

            # Return the buffer to the sink’s free queue:
            try:
                buf.release()
            except:
                pass

            # Small throttle so the loop isn’t 100% CPU locked
            time.sleep(0.005)

        # 6) Clean up when _running becomes False
        try:
            if self.queue_sink:
                self.grabber.stream_stop()
        except:
            pass

        try:
            self.grabber.device_close()
        except:
            pass

    def stop(self):
        """Signal the thread to end the grab loop cleanly."""
        self._running = False
        # wait for run() loop to exit
        self.wait()