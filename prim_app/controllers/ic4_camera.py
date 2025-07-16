import importlib
from PyQt5.QtGui import QImage
from .interfaces import ICameraController


class IC4CameraController(ICameraController):
    """Controller wrapper around imagingcontrol4 Grabber."""

    def __init__(self, device_info=None):
        self.device_info = device_info
        self.ic4 = importlib.import_module("imagingcontrol4")
        self.grabber = None

    def initialize(self):
        self.ic4.Library.init()
        self.grabber = self.ic4.Grabber()
        self.grabber.device_open(self.device_info)

    def arm_trigger(self):
        trig_node = self.grabber.device_property_map.find_enumeration("TriggerMode")
        if trig_node:
            trig_node.value = "External"

    def grab_frame(self):
        buf = self.grabber.snap_image()
        arr = buf.numpy_wrap()
        qimg = QImage(arr.data, arr.shape[1], arr.shape[0], arr.strides[0], QImage.Format_Grayscale8)
        return qimg.copy(), buf

    def close(self):
        if self.grabber and self.grabber.is_device_open:
            self.grabber.device_close()
        self.grabber = None
