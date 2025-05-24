from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage


class SDKCameraThread(QThread):
    """
    Thread to grab live frames from a DMK camera using IC Imaging Control 4.
    Expects the GenTL producer to be loaded and ic4.Library initialized externally.
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
        self.grabber = None
        self.ic4 = None

    def apply_node_settings(self, settings: dict):
        """
        Apply camera node settings (defaults or advanced) to the open device.
        """
        if not self.grabber or not self.ic4:
            return
        for name, val in settings.items():
            try:
                prop_id = getattr(self.ic4.PropId, name)
                self.grabber.device_property_map.set_value(prop_id, val)
            except Exception as e:
                self.camera_error.emit(f"Failed to set {name} → {val}: {e}", "")

    def run(self):
        try:
            # Import IC4 after CTI and init have been done outside
            import imagingcontrol4 as ic4

            self.ic4 = ic4

            # Create grabber
            grabber = ic4.Grabber()
            self.grabber = grabber

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

            # Configure frame rate
            prop_map = grabber.device_property_map
            try:
                prop_map.set_value(ic4.PropId.ACQUISITION_FRAME_RATE, self.fps)
            except Exception:
                pass

            # Notify UI of current resolution
            width = prop_map.get_value(ic4.PropId.WIDTH)
            height = prop_map.get_value(ic4.PropId.HEIGHT)
            self.resolutions_updated.emit([f"{width}x{height}"])

            # Setup high-throughput queue sink
            sink = ic4.QueueSink()
            grabber.stream_setup(
                sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            grabber.acquisition_start()

            # Streaming loop
            while not self._stop_requested:
                try:
                    buffer = sink.pop_output_buffer(1000)
                except Exception:
                    continue
                if buffer:
                    arr = buffer.numpy_wrap()
                    # Convert to QImage
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
                        mono = arr[..., 0] if arr.ndim == 3 else arr
                        qimg = QImage(
                            mono.data,
                            mono.shape[1],
                            mono.shape[0],
                            mono.strides[0],
                            QImage.Format_Indexed8,
                        )
                    self.frame_ready.emit(qimg.copy(), arr)
                    buffer.release()

            # Teardown
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
