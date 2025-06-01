import logging
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QCheckBox, QSlider
from PyQt5.QtCore import Qt, pyqtSignal

log = logging.getLogger(__name__)


class CameraControlPanel(QWidget):
    # Signal: name, value, backend ('opencv' or 'ic4')
    property_changed_backend = pyqtSignal(str, float, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEnabled(False)
        self.backend = "opencv"  # Default — will be set by main_window.py

        layout = QVBoxLayout(self)

        # --- Auto Exposure Checkbox ---
        self.auto_exposure_checkbox = QCheckBox("Auto Exposure")
        self.auto_exposure_checkbox.stateChanged.connect(self._on_auto_exposure_changed)
        layout.addWidget(self.auto_exposure_checkbox)

        # --- Gain Slider ---
        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setMinimum(0)
        self.gain_slider.setMaximum(255)
        self.gain_slider.setTickInterval(1)
        self.gain_slider.valueChanged.connect(self._on_gain_changed)

        layout.addWidget(QLabel("Gain"))
        layout.addWidget(self.gain_slider)

        self.auto_exposure_checkbox.setEnabled(False)
        self.gain_slider.setEnabled(False)

    def update_controls_from_camera(self, prop_dict: dict):
        """Update the UI based on detected camera properties."""
        ae = prop_dict.get("AutoExposure", -1.0)
        gain = prop_dict.get("Gain", 0)

        self.auto_exposure_checkbox.blockSignals(True)
        self.gain_slider.blockSignals(True)

        self.auto_exposure_checkbox.setChecked(ae >= 0.5)
        self.gain_slider.setValue(int(gain))

        self.setEnabled(True)
        self.auto_exposure_checkbox.setEnabled(True)
        self.gain_slider.setEnabled(True)

        self.auto_exposure_checkbox.blockSignals(False)
        self.gain_slider.blockSignals(False)

        log.debug(f"[UI Sync] AE={ae}, Gain={gain}")

    def set_backend(self, backend_name: str):
        """Set control routing to either 'opencv' or 'ic4'."""
        self.backend = backend_name
        log.info(f"[CameraControlPanel] Backend set to: {backend_name}")

    def _on_auto_exposure_changed(self, state):
        value = 0.75 if state == Qt.Checked else 0.25
        self.property_changed_backend.emit("AutoExposure", value, self.backend)
        log.debug(f"[UI → {self.backend}] AutoExposure set to {value}")

    def _on_gain_changed(self, value):
        self.property_changed_backend.emit("Gain", float(value), self.backend)
        log.debug(f"[UI → {self.backend}] Gain set to {value}")
