# File: prim_app/ui/control_panels/camera_control_panel.py

import logging
import imagingcontrol4 as ic4
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QSlider, QHBoxLayout, QCheckBox, QFormLayout
from PyQt5.QtCore import Qt, pyqtSignal

log = logging.getLogger(__name__)

class CameraControlPanel(QWidget):
    """
    Builds sliders/checkboxes for gain, exposure, brightness, etc. once the Grabber is open.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grabber = None
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.main_layout)

        # Placeholder label until we build controls:
        self.info_label = QLabel("Camera controls will appear here.")
        self.main_layout.addWidget(self.info_label)

    def _on_grabber_ready(self):
        """
        Called by MainWindow once the Grabber is open and streaming is set up.
        We now have: self.grabber → open ic4.Grabber
        We want to build dynamic controls for available features (ExposureTime, Gain, etc.)
        """

        if not self.grabber or not self.grabber.is_device_open:
            log.error("CameraControlPanel: _on_grabber_ready() called, but grabber is not open.")
            return

        # Clear any old widgets:
        for i in reversed(range(self.main_layout.count())):
            self.main_layout.itemAt(i).widget().deleteLater()

        prop_map = self.grabber.device_property_map

        # We will scan all properties in prop_map, and pick out enumeration‐type ones
        enum_features = []
        float_features = []
        int_features = []

        # The current binding lets us iterate over prop_map (each item is a Property)
        for prop in prop_map:
            # Each prop has attributes: prop.prop_type (PropType), prop.name, prop.visibility, etc.
            ptype = prop.prop_type
            if ptype == ic4.PropertyType.Enumeration:
                enum_features.append(prop)
            elif ptype == ic4.PropertyType.Integer:
                int_features.append(prop)
            elif ptype == ic4.PropertyType.Float:
                float_features.append(prop)
            # you can also catch Boolean or Command if you want checkboxes/buttons

        form = QFormLayout()
        form.setContentsMargins(4, 4, 4, 4)
        form.setSpacing(6)

        # Build sliders/combos for enumeration features first:
        for enum_prop in enum_features:
            # e.g. PixelFormat, AcquisitionMode, ExposureAuto, GainAuto, etc.
            try:
                label = QLabel(enum_prop.name)
                combo = QComboBox()
                for entry in enum_prop.entries:
                    combo.addItem(entry.name)
                # set current
                combo.setCurrentText(enum_prop.value)
                combo.currentTextChanged.connect(
                    lambda txt, ep=enum_prop: setattr(ep, "value", txt)
                )
                form.addRow(label, combo)
            except Exception as e:
                log.error(f"Failed to build enum control for {enum_prop.name}: {e}")

        # Build sliders for integer features (if they have increment info)
        for int_prop in int_features:
            try:
                label = QLabel(int_prop.name)
                slider = QSlider(Qt.Horizontal)
                slider.setMinimum(int(int_prop.min))
                slider.setMaximum(int(int_prop.max))
                step = int_prop.increment if int_prop.increment else 1
                slider.setSingleStep(int(step))
                slider.setValue(int(int_prop.value))
                slider.valueChanged.connect(
                    lambda v, ip=int_prop: setattr(ip, "value", v)
                )
                form.addRow(label, slider)
            except Exception as e:
                log.error(f"Failed to build integer control for {int_prop.name}: {e}")

        # Build sliders for float features (if they have increment and min/max)
        for float_prop in float_features:
            try:
                label = QLabel(float_prop.name)
                slider = QSlider(Qt.Horizontal)
                # Convert float range into integer steps
                minv = float_prop.min
                maxv = float_prop.max
                inc = float_prop.increment or 1.0
                steps = int(round((maxv - minv) / inc))
                slider.setMinimum(0)
                slider.setMaximum(steps)
                # map current value → "position"
                curpos = int(round((float_prop.value - minv) / inc))
                slider.setValue(curpos)

                def on_float_change(pos, fp=float_prop):
                    newval = minv + pos * inc
                    fp.value = newval

                slider.valueChanged.connect(on_float_change)
                form.addRow(label, slider)
            except Exception as e:
                log.error(f"Failed to build float control for {float_prop.name}: {e}")

        self.main_layout.addLayout(form)