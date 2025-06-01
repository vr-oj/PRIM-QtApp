# prim_app/ui/control_panels/camera_control_panel.py

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QCheckBox,
    QSlider,
    QHBoxLayout,
)
from PyQt5.QtCore import Qt, pyqtSignal
import logging

log = logging.getLogger(__name__)


class CameraControlPanel(QWidget):
    # This signal is emitted when the user changes a property via UI
    property_changed = pyqtSignal(str, float)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setEnabled(False)
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        # Auto Exposure
        self.auto_exposure_checkbox = QCheckBox("Auto Exposure")
        self.auto_exposure_checkbox.stateChanged.connect(self._on_auto_exposure_changed)
        self.layout.addWidget(self.auto_exposure_checkbox)

        # Gain
        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setMinimum(0)
        self.gain_slider.setMaximum(255)
        self.gain_slider.setValue(0)
        self.gain_slider.setTickInterval(1)
        self.gain_slider.valueChanged.connect(self._on_gain_changed)
        self.layout.addWidget(QLabel("Gain"))
        self.layout.addWidget(self.gain_slider)

        # Brightness
        self.brightness_slider = QSlider(Qt.Horizontal)
        self.brightness_slider.setMinimum(0)
        self.brightness_slider.setMaximum(255)
        self.brightness_slider.setValue(0)
        self.brightness_slider.setTickInterval(1)
        self.brightness_slider.valueChanged.connect(self._on_brightness_changed)
        self.layout.addWidget(QLabel("Brightness"))
        self.layout.addWidget(self.brightness_slider)

    def update_controls_from_camera(self, prop_dict: dict):
        """Update the UI to reflect camera properties."""
        ae = prop_dict.get("AutoExposure", 1.0)
        ae = 1.0 if ae in [1, 1.0, True] else 0.0  # Normalize value
        gain = prop_dict.get("Gain", 0)
        brightness = prop_dict.get("Brightness", 0)

        self.auto_exposure_checkbox.blockSignals(True)
        self.gain_slider.blockSignals(True)
        self.brightness_slider.blockSignals(True)

        self.auto_exposure_checkbox.setChecked(ae > 0)
        self.gain_slider.setValue(int(gain))
        self.brightness_slider.setValue(int(brightness))

        self.setEnabled(True)
        self.auto_exposure_checkbox.setEnabled(True)
        self.gain_slider.setEnabled(True)
        self.brightness_slider.setEnabled(True)

        self.auto_exposure_checkbox.blockSignals(False)
        self.gain_slider.blockSignals(False)
        self.brightness_slider.blockSignals(False)

        log.debug(f"[UI Sync] AE={ae > 0}, Gain={gain}, Brightness={brightness}")

    def _on_auto_exposure_changed(self, state):
        value = 1.0 if state == Qt.Checked else 0.0
        self.property_changed.emit("AutoExposure", value)
        log.debug(f"[UI → Cam] AutoExposure set to {value}")

    def _on_gain_changed(self, value):
        self.property_changed.emit("Gain", float(value))
        log.debug(f"[UI → Cam] Gain set to {value}")

    def _on_brightness_changed(self, value):
        self.property_changed.emit("Brightness", float(value))
        log.debug(f"[UI → Cam] Brightness set to {value}")
