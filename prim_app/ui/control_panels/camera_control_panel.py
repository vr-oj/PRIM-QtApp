# ─── ui/control_panels/camera_control_panel.py ─────────────────────────────

import logging
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QSlider, QComboBox
from PyQt5.QtCore import Qt

log = logging.getLogger(__name__)


class CameraControlPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.grabber = None
        self.layout = QVBoxLayout(self)
        self.layout.addWidget(QLabel("Camera Controls"))
        # We will fill this in once grabber_ready arrives
        self.setLayout(self.layout)

    def _on_grabber_ready(self):
        """
        Called by MainWindow once the grabber is open & streaming.
        We can now read self.grabber.device_property_map and build controls.
        """

        # Clear any old controls
        for i in reversed(range(self.layout.count())):
            widget = self.layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        self.layout.addWidget(QLabel("Camera Controls"))

        prop_map = self.grabber.device_property_map

        # ─── Example: build a dropdown for PixelFormat ──────────────────────
        try:
            pf_node = prop_map.find_enumeration("PixelFormat")
            if pf_node:
                pf_combo = QComboBox(self)
                pf_combo.addItem(f"Current: {pf_node.value}", pf_node.value)
                for entry in pf_node.entries:
                    pf_combo.addItem(entry.name, entry.name)
                pf_combo.currentTextChanged.connect(
                    lambda txt: self._set_enumeration(pf_node, txt)
                )
                self.layout.addWidget(QLabel("Pixel Format:"))
                self.layout.addWidget(pf_combo)
        except Exception as ex:
            log.error(f"Could not add PixelFormat control: {ex}")

        # ─── Example: build a slider for “ExposureTime” if available ───────
        try:
            exp_node = prop_map.find_integer("ExposureTime")
            if exp_node:
                slider = QSlider(Qt.Horizontal, self)
                slider.setMinimum(exp_node.min)
                slider.setMaximum(exp_node.max)
                slider.setValue(exp_node.value)
                slider.setTickInterval(exp_node.increment or 1)
                slider.setSingleStep(exp_node.increment or 1)
                slider.valueChanged.connect(lambda v: setattr(exp_node, "value", v))
                self.layout.addWidget(QLabel("Exposure Time:"))
                self.layout.addWidget(slider)
        except Exception as ex:
            log.error(f"Could not add ExposureTime control: {ex}")

        # ─── Example: build a slider for “Gain” (float) if available ───────
        try:
            gain_node = prop_map.find_float("Gain")
            if gain_node:
                slider = QSlider(Qt.Horizontal, self)
                # Map float → slider range by multiplying by 100 (for example)
                slider.setMinimum(int(gain_node.min * 100))
                slider.setMaximum(int(gain_node.max * 100))
                slider.setValue(int(gain_node.value * 100))
                slider.setTickInterval(int(gain_node.increment * 100) or 1)
                slider.setSingleStep(int(gain_node.increment * 100) or 1)

                def on_gain_changed(val):
                    gain_node.value = float(val / 100.0)

                slider.valueChanged.connect(on_gain_changed)
                self.layout.addWidget(QLabel("Gain:"))
                self.layout.addWidget(slider)
        except Exception as ex:
            log.error(f"Could not add Gain control: {ex}")

        # ─── Example: build a checkbox for “AutoExposure” (boolean) if available ─
        try:
            ae_node = prop_map.find_boolean("AutoExposure")
            if ae_node:
                from PyQt5.QtWidgets import QCheckBox

                cb = QCheckBox("Auto‐Exposure", self)
                cb.setChecked(ae_node.value)
                cb.stateChanged.connect(lambda st: setattr(ae_node, "value", bool(st)))
                self.layout.addWidget(cb)
        except Exception as ex:
            log.error(f"Could not add AutoExposure control: {ex}")

        # … repeat for any other nodes you care about (e.g. WhiteBalance, Gamma, etc.) …

        self.layout.addStretch(1)

    def _set_enumeration(self, node, selected_name):
        try:
            node.value = selected_name
        except Exception as ex:
            log.error(
                f"Failed to set enumeration {node.name!r} = {selected_name}: {ex}"
            )
