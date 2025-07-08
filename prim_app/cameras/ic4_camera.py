import imagingcontrol4 as ic4
import numpy as np

from .base import CameraBase


class IC4Camera(CameraBase):
    """Camera backend using The Imaging Source IC4 SDK."""

    def __init__(self, device_info: ic4.DeviceInfo):
        self.device_info = device_info
        self.grabber = None
        self._sink = None

    def connect(self):
        ic4.Library.init()
        self.grabber = ic4.Grabber()
        self.grabber.device_open(self.device_info)

    def disconnect(self):
        if self.grabber and self.grabber.is_device_open:
            if self._sink:
                self.grabber.stream_stop()
                self._sink = None
            self.grabber.device_close()
        self.grabber = None

    def start_stream(self):
        if not self.grabber:
            raise RuntimeError("Grabber not open")
        self._sink = ic4.QueueSink(self, [ic4.PixelFormat.Mono8], max_output_buffers=1)
        from imagingcontrol4 import StreamSetupOption

        self.grabber.stream_setup(self._sink, setup_option=StreamSetupOption.ACQUISITION_START)

    def stop_stream(self):
        if self.grabber and self._sink:
            self.grabber.stream_stop()
            self._sink = None

    def get_frame(self):
        if not self._sink:
            return None
        buf = self._sink.pop_output_buffer()
        arr = buf.numpy_wrap()
        if arr.dtype != np.uint8:
            max_val = float(arr.max()) if arr.max() > 0 else 1.0
            scale = 255.0 / max_val
            arr = (arr.astype(np.float32) * scale).astype(np.uint8)
        return arr

    def set_property(self, prop_name: str, value):
        if not self.grabber:
            return False
        props = self.grabber.device_property_map
        node = None
        for finder in ("find_float", "find_integer", "find_enumeration"):
            fn = getattr(props, finder, None)
            if fn:
                try:
                    node = fn(prop_name)
                    if node:
                        break
                except Exception:
                    pass
        if node is None:
            return False
        try:
            node.value = value
            return True
        except Exception:
            return False
