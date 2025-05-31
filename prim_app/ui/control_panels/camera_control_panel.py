# prim_app/ui/control_panels/camera_control_panel.py

import logging
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QSlider,
    QCheckBox,
    QHBoxLayout,
    QSpinBox,
    QGroupBox,
    QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot

log = logging.getLogger(__name__)


class CameraControlPanel(QWidget):
    property_changed = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self._init_ui()
        self._connect_signals()
        self.setEnabled(False)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Auto Exposure
        self.auto_exposure_checkbox = QCheckBox("Auto Exposure")
        layout.addWidget(self.auto_exposure_checkbox)

        # Gain controls
        self.gain_group = QGroupBox("Gain")
        gain_layout = QHBoxLayout()
        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setRange(0, 255)
        self.gain_spinbox = QSpinBox()
        self.gain_spinbox.setRange(0, 255)
        gain_layout.addWidget(self.gain_slider)
        gain_layout.addWidget(self.gain_spinbox)
        self.gain_group.setLayout(gain_layout)
        layout.addWidget(self.gain_group)

        # Brightness controls
        self.brightness_group = QGroupBox("Brightness")
        brightness_layout = QHBoxLayout()
        self.brightness_slider = QSlider(Qt.Horizontal)
        self.brightness_slider.setRange(0, 255)
        self.brightness_spinbox = QSpinBox()
        self.brightness_spinbox.setRange(0, 255)
        brightness_layout.addWidget(self.brightness_slider)
        brightness_layout.addWidget(self.brightness_spinbox)
        self.brightness_group.setLayout(brightness_layout)
        layout.addWidget(self.brightness_group)

        layout.addStretch()

    def _connect_signals(self):
        # Auto Exposure toggle
        self.auto_exposure_checkbox.toggled.connect(self._on_auto_exposure_toggled)

        # Gain sync
        self.gain_slider.valueChanged.connect(self.gain_spinbox.setValue)
        self.gain_spinbox.valueChanged.connect(self.gain_slider.setValue)
        self.gain_slider.sliderReleased.connect(self._on_gain_changed)
        self.gain_spinbox.editingFinished.connect(self._on_gain_changed)

        # Brightness sync
        self.brightness_slider.valueChanged.connect(self.brightness_spinbox.setValue)
        self.brightness_spinbox.valueChanged.connect(self.brightness_slider.setValue)
        self.brightness_slider.sliderReleased.connect(self._on_brightness_changed)
        self.brightness_spinbox.editingFinished.connect(self._on_brightness_changed)

    def _on_auto_exposure_toggled(self, checked):
        # Only allow manual controls if AE is off
        self.gain_group.setEnabled(not checked)
        self.brightness_group.setEnabled(not checked)
        self.property_changed.emit("AutoExposure", checked)
        log.debug(f"Auto Exposure toggled: {'ON' if checked else 'OFF'}")

    def _on_gain_changed(self):
        value = self.gain_slider.value()
        self.property_changed.emit("Gain", value)
        log.debug(f"Gain changed to: {value}")

    def _on_brightness_changed(self):
        value = self.brightness_slider.value()
        self.property_changed.emit("Brightness", value)
        log.debug(f"Brightness changed to: {value}")

    @pyqtSlot(dict)
    def update_camera_properties(self, props: dict):
        """Receive and reflect camera properties (from thread)"""
        if not props:
            self.setEnabled(False)
            return

        self.setEnabled(True)

        gain = int(props.get("Gain", 0))
        brightness = int(props.get("Brightness", 0))
        auto_exp_val = props.get("AutoExposure", 0.25)
        auto_exp = auto_exp_val >= 0.5

        self.auto_exposure_checkbox.setChecked(auto_exp)
        self.gain_slider.setValue(gain)
        self.brightness_slider.setValue(brightness)
        self.gain_group.setEnabled(not auto_exp)
        self.brightness_group.setEnabled(not auto_exp)

        log.debug(f"[UI Sync] AE={auto_exp}, Gain={gain}, Brightness={brightness}")
