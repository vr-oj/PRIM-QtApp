import logging
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QFormLayout,
    QCheckBox,
    QSlider,
    QLabel,
    QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSlot

log = logging.getLogger(__name__)


class CameraControlPanel(QWidget):
    def __init__(self, ic4_controller=None, parent=None):
        super().__init__(parent)
        self.ic4_controller = ic4_controller
        self._init_ui()
        self._connect_signals()
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        self.form = QFormLayout()

        # Auto Exposure Toggle
        self.auto_exposure_checkbox = QCheckBox("Auto Exposure")
        self.auto_exposure_checkbox.setChecked(True)
        self.form.addRow("Auto Exposure", self.auto_exposure_checkbox)

        # Gain Slider
        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setMinimum(0)
        self.gain_slider.setMaximum(255)
        self.gain_slider.setValue(128)
        self.gain_label = QLabel("128")
        gain_layout = QVBoxLayout()
        gain_layout.addWidget(self.gain_slider)
        gain_layout.addWidget(self.gain_label)
        self.form.addRow("Gain", gain_layout)

        layout.addLayout(self.form)

    def _connect_signals(self):
        self.auto_exposure_checkbox.toggled.connect(self._on_auto_exposure_changed)
        self.gain_slider.valueChanged.connect(self._on_gain_changed)

    @pyqtSlot(bool)
    def _on_auto_exposure_changed(self, enabled):
        log.debug(f"[UI → ic4] Auto Exposure set to {enabled}")
        if self.ic4_controller:
            self.ic4_controller.set_auto_exposure(enabled)

    @pyqtSlot(int)
    def _on_gain_changed(self, value):
        self.gain_label.setText(str(value))
        log.debug(f"[UI → ic4] Gain set to {value}")
        if self.ic4_controller:
            self.ic4_controller.set_gain(value)

    def sync_ui_with_camera(self):
        if not self.ic4_controller:
            return
        props = self.ic4_controller.get_all_properties()
        ae_val = props.get("Auto Exposure", "Off")
        gain_val = props.get("Gain", 128)
        self.auto_exposure_checkbox.setChecked(ae_val in ["On", "Continuous"])
        self.gain_slider.setValue(int(gain_val))
        log.debug(f"[UI Sync] AE={ae_val}, Gain={gain_val}")
