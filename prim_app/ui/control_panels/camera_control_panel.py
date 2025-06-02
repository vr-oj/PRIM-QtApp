# ui/control_panels/camera_control_panel.py

import logging
import imagingcontrol4 as ic4
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QSlider, QHBoxLayout
from PyQt5.QtCore import Qt, pyqtSlot

log = logging.getLogger(__name__)

class CameraControlPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.grabber = None       # type: ic4.Grabber
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0,0,0,0)
        self.layout.setSpacing(4)

    def _on_grabber_ready(self):
        """
        Called by MainWindow once the camera is open.
        We now have: self.grabber = <ic4.Grabber> and we can 
        poke at grabber.device_property_map to build sliders.
        """
        if self.grabber is None:
            return

        prop_map = self.grabber.device_property_map

        # Enumerate all enumeration properties
        enum_names = [p.name for p in prop_map.enumerations()]
        log.info(f"====== Available Enumeration Properties: {enum_names}")

        # Example: try to build a Gain slider if it exists
        try:
            gain_prop = prop_map.find_float("Gain")
            if gain_prop:
                slider = QSlider(Qt.Horizontal)
                slider.setMinimum(int(gain_prop.min))
                slider.setMaximum(int(gain_prop.max))
                try:
                    slider.setSingleStep(int(gain_prop.increment))
                except ic4.IC4Exception:
                    pass
                slider.setValue(int(gain_prop.value))
                slider.valueChanged.connect(lambda v: gain_prop.set_value(v))
                label = QLabel("Gain")
                wnd = QHBoxLayout()
                wnd.addWidget(label)
                wnd.addWidget(slider)
                self.layout.addLayout(wnd)
        except Exception as e:
            log.error(f"Failed to build Gain control: {e}")

        # Repeat for ExposureTime, Brightness, Auto‐Exposure, etc.,
        # always wrapping increment/min/max in try/except GenICamNotImplemented.