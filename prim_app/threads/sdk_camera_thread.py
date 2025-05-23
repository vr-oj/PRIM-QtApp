# sdk_thread.py
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage


class SDKCameraThread(QThread):
    """
    Thread to grab live frames from a DMK camera using IC Imaging Control 4.
    Emits high-quality QImage frames and raw numpy arrays.
    """

    # Emitted with the current QImage and the raw numpy array
    frame_ready = pyqtSignal(QImage, object)
    # Emitted when supported resolutions update
    resolutions_updated = pyqtSignal(list)
    # Emitted when camera properties (e.g. exposure, gain) update
    properties_updated = pyqtSignal(dict)
    # Emitted on errors: (message, error_code)
    camera_error = pyqtSignal(str, str)

    def __init__(self, device_name=None, fps=10, parent=None):
        super().__init__(parent)
        self.device_name = device_name
        self.fps = fps
        self._stop_requested = False

    def run(self):
        try:
            # Initialize the IC4 library
            ic4.Library.init()
            grabber = ic4.Grabber()

            # Enumerate and open device
            devices = ic4.DeviceEnum.devices()
            if not devices:
                raise RuntimeError("No camera devices found")

            if self.device_name:
                dev_info = next(
                    (d for d in devices if self.device_name in d.unique_name), None
                )
                if not dev_info:
                    raise RuntimeError(f"Camera '{self.device_name}' not found")
            else:
                dev_info = devices[0]

            grabber.device_open(dev_info)

            # Configure resolution and frame rate
            prop_map = grabber.device_property_map
            width = prop_map.get_value(ic4.PropId.WIDTH)
            height = prop_map.get_value(ic4.PropId.HEIGHT)
            prop_map.set_value(ic4.PropId.ACQUISITION_FRAME_RATE, self.fps)

            # Notify UI of current resolution
            self.resolutions_updated.emit([f"{width}x{height}"])

            # Set up a queue sink for continuous high-throughput streaming
            sink = ic4.QueueSink()
            grabber.stream_setup(
                sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            grabber.acquisition_start()

            # Main loop: retrieve buffers and emit frames
            while not self._stop_requested:
                try:
                    buffer = sink.pop_output_buffer(1000)  # timeout in ms
                except ic4.IC4Exception:
                    continue

                if buffer:
                    # Create numpy view (no copy) of image data
                    arr = buffer.numpy_wrap()

                    # Convert BGR to RGB if needed
                    if arr.ndim == 3 and arr.shape[2] == 3:
                        rgb = arr[..., ::-1]
                        qimg = QImage(
                            rgb.data,
                            rgb.shape[1],
                            rgb.shape[0],
                            rgb.strides[0],
                            QImage.Format_RGB888,
                        )
                    else:
                        # Mono8 or single channel
                        mono = arr[..., 0] if arr.ndim == 3 else arr
                        qimg = QImage(
                            mono.data,
                            mono.shape[1],
                            mono.shape[0],
                            mono.strides[0],
                            QImage.Format_Indexed8,
                        )

                    # Emit a copy to decouple the buffer
                    self.frame_ready.emit(qimg.copy(), arr)
                    buffer.release()

            # Tear down stream
            grabber.acquisition_stop()
            grabber.stream_stop()
            grabber.device_close()

        except Exception as ex:
            code = getattr(ex, "code", None)
            self.camera_error.emit(str(ex), code.name if code else "")

    def stop(self):
        """Request thread shutdown and wait for termination."""
        self._stop_requested = True
        self.wait()
