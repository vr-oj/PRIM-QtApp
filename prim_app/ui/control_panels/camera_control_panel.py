# prim_app/ui/control_panels/camera_control_panel.py

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QCheckBox,
    QSlider,
)
from PyQt5.QtCore import Qt, pyqtSignal
import logging

log = logging.getLogger(__name__)


class CameraControlPanel(QWidget):
    property_changed = pyqtSignal(str, float)  # Signal for property updates

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setEnabled(False)
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        # --- Auto Exposure Toggle ---
        self.auto_exposure_checkbox = QCheckBox("Auto Exposure")
        self.auto_exposure_checkbox.stateChanged.connect(self._on_auto_exposure_changed)
        self.layout.addWidget(self.auto_exposure_checkbox)

        # --- Gain Slider ---
        self.layout.addWidget(QLabel("Gain"))
        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setMinimum(0)
        self.gain_slider.setMaximum(255)
        self.gain_slider.setValue(0)
        self.gain_slider.setTickInterval(1)
        self.gain_slider.setEnabled(False)
        self.gain_slider.valueChanged.connect(self._on_gain_changed)
        self.layout.addWidget(self.gain_slider)

        # --- Brightness Slider ---
        self.layout.addWidget(QLabel("Brightness"))
        self.brightness_slider = QSlider(Qt.Horizontal)
        self.brightness_slider.setMinimum(0)
        self.brightness_slider.setMaximum(255)
        self.brightness_slider.setValue(0)
        self.brightness_slider.setTickInterval(1)
        self.brightness_slider.setEnabled(False)
        self.brightness_slider.valueChanged.connect(self._on_brightness_changed)
        self.layout.addWidget(self.brightness_slider)

    def update_controls_from_camera(self, prop_dict: dict):
        """Sync UI with camera state."""
        ae = prop_dict.get("AutoExposure", 1.0)
        gain = prop_dict.get("Gain", 0)
        brightness = prop_dict.get("Brightness", 0)

        # Interpret AE state
        is_auto_exposure = ae >= 0.5

        # Block signals during sync
        self.auto_exposure_checkbox.blockSignals(True)
        self.gain_slider.blockSignals(True)
        self.brightness_slider.blockSignals(True)

        self.auto_exposure_checkbox.setChecked(is_auto_exposure)
        self.gain_slider.setValue(int(gain))
        self.brightness_slider.setValue(int(brightness))

        self.gain_slider.setEnabled(not is_auto_exposure)
        self.brightness_slider.setEnabled(not is_auto_exposure)
        self.setEnabled(True)

        # Re-enable signals
        self.auto_exposure_checkbox.blockSignals(False)
        self.gain_slider.blockSignals(False)
        self.brightness_slider.blockSignals(False)

        log.debug(
            f"[UI Sync] AE={is_auto_exposure}, Gain={gain}, Brightness={brightness}"
        )

    def _on_auto_exposure_changed(self, state):
        is_checked = state == Qt.Checked
        value = 0.75 if is_checked else 0.25
        self.property_changed.emit("AutoExposure", value)
        log.debug(f"[UI → Cam] AutoExposure set to {value}")

        # Enable/disable sliders based on AE state
        self.gain_slider.setEnabled(not is_checked)
        self.brightness_slider.setEnabled(not is_checked)

    def _on_gain_changed(self, value):
        self.property_changed.emit("Gain", float(value))
        log.debug(f"[UI → Cam] Gain set to {value}")

    def _on_brightness_changed(self, value):
        self.property_changed.emit("Brightness", float(value))
        log.debug(f"[UI → Cam] Brightness set to {value}")
