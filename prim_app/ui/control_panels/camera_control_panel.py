# prim_app/ui/control_panels/camera_control_panel.py

import logging
import imagingcontrol4 as ic4
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QSlider, QCheckBox, QFormLayout
)
from PyQt5.QtCore import Qt

log = logging.getLogger(__name__)

class CameraControlPanel(QWidget):
    """
    After the Grabber is open, we query its property map and build 
    sliders/check boxes for gain, exposure, etc.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grabber = None  # will be set by MainWindow._on_grabber_ready()

        # We'll lay out “Gain”, “Exposure”, “PixelFormat” etc. here:
        self.main_layout = QFormLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(6)

    def _on_grabber_ready(self):
        """
        Called once MainWindow hands us an open grabber.  We can ask
        grabber.device_property_map for all available properties and build
        the appropriate widgets.
        """
        if self.grabber is None:
            log.error("CameraControlPanel: no grabber set in _on_grabber_ready().")
            return

        prop_map = self.grabber.device_property_map

        # Clear any old controls:
        while self.main_layout.count():
            child = self.main_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # List out all properties in this map:
        for prop in prop_map.properties():
            name = prop.name  # e.g. "Gain", "ExposureTime", "PixelFormat"
            # Depending on property type, build the right widget:
            if isinstance(prop, ic4.PropInteger):
                # Build a slider for integer‐valued properties
                slider = QSlider(Qt.Horizontal, self)
                slider.setMinimum(prop.min_value)
                slider.setMaximum(prop.max_value)
                try:
                    slider.setSingleStep(int(prop.increment))
                except ic4.IC4Exception:
                    slider.setSingleStep(1)
                slider.setValue(prop.value)
                slider.valueChanged.connect(
                    lambda val, p=prop: p.set_value(val)
                )
                self.main_layout.addRow(f"{name}:", slider)

            elif isinstance(prop, ic4.PropFloat):
                # Build a small slider for float (maps float→int for UI, or use QDoubleSpinBox)
                spin = QLabel(f"{prop.value:.2f}", self)
                # If you want a QDoubleSpinBox instead:
                # from PyQt5.QtWidgets import QDoubleSpinBox
                # spin = QDoubleSpinBox(self)
                # spin.setMinimum(prop.min_value)
                # spin.setMaximum(prop.max_value)
                # try:
                #     spin.setSingleStep(prop.increment)
                # except ic4.IC4Exception:
                #     spin.setSingleStep((prop.max_value - prop.min_value)/100.0)
                # spin.setValue(prop.value)
                # spin.valueChanged.connect(lambda v, p=prop: p.set_value(v))
                self.main_layout.addRow(f"{name}:", spin)

            elif isinstance(prop, ic4.PropBoolean):
                # Build a checkbox for boolean properties
                cb = QCheckBox(self)
                cb.setChecked(bool(prop.value))
                cb.stateChanged.connect(lambda state, p=prop: p.set_value(bool(state)))
                self.main_layout.addRow(f"{name}:", cb)

            elif isinstance(prop, ic4.PropEnumeration):
                # Build a dropdown for enumerations
                combo = QLabel(f"{prop.value}", self)
                # For a full implementation you’d add QComboBox and fill it with prop.entries:
                # from PyQt5.QtWidgets import QComboBox
                # combo = QComboBox(self)
                # for entry in prop.entries:
                #     combo.addItem(entry.name)
                # combo.setCurrentText(prop.value)
                # combo.currentTextChanged.connect(lambda text, p=prop: p.set_value(text))
                self.main_layout.addRow(f"{name}:", combo)

            else:
                # Unhandled property types can be shown as a simple label
                lbl = QLabel(f"(unsupported type)", self)
                self.main_layout.addRow(f"{name}:", lbl)

        # Finally, enable the panel now that it's built:
        self.setEnabled(True)