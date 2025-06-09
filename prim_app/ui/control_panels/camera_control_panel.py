import logging
import math

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget,
    QFormLayout,
    QLabel,
    QDoubleSpinBox,
    QCheckBox,
    QComboBox,
    QSlider,
    QHBoxLayout,
)

from imagingcontrol4 import IC4Exception

log = logging.getLogger(__name__)


class CameraControlPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.grabber = None
        self.is_recording = False
        self._exp_scale = 1
        self._gain_scale = 1

        self.layout = QFormLayout(self)
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.layout.setSpacing(6)

        self.exposure_label = QLabel("Exposure (µs):")
        self.exposure_spin = QDoubleSpinBox()
        self.exposure_spin.setDecimals(1)
        self.exposure_spin.setSuffix(" µs")
        self.exposure_spin.setEnabled(False)
        self.exposure_spin.valueChanged.connect(self._on_exposure_changed)

        self.exposure_slider = QSlider(Qt.Horizontal)
        self.exposure_slider.setEnabled(False)
        self.exposure_slider.valueChanged.connect(
            lambda v: self.exposure_spin.setValue(v / self._exp_scale)
        )

        exp_row = QWidget()
        exp_layout = QHBoxLayout(exp_row)
        exp_layout.setContentsMargins(0, 0, 0, 0)
        exp_layout.addWidget(self.exposure_slider)
        exp_layout.addWidget(self.exposure_spin)
        self.layout.addRow(self.exposure_label, exp_row)

        self.gain_label = QLabel("Gain:")
        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setDecimals(2)
        self.gain_spin.setEnabled(False)
        self.gain_spin.valueChanged.connect(self._on_gain_changed)

        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setEnabled(False)
        self.gain_slider.valueChanged.connect(
            lambda v: self.gain_spin.setValue(v / self._gain_scale)
        )

        gain_row = QWidget()
        gain_layout = QHBoxLayout(gain_row)
        gain_layout.setContentsMargins(0, 0, 0, 0)
        gain_layout.addWidget(self.gain_slider)
        gain_layout.addWidget(self.gain_spin)
        self.layout.addRow(self.gain_label, gain_row)

        self.ae_checkbox = QCheckBox("Auto Exposure")
        self.ae_checkbox.setEnabled(False)
        self.ae_checkbox.stateChanged.connect(self._on_auto_exposure_toggled)
        self.layout.addRow(self.ae_checkbox)

        self.ag_checkbox = QCheckBox("Auto Gain")
        self.ag_checkbox.setEnabled(False)
        self.ag_checkbox.stateChanged.connect(self._on_auto_gain_toggled)
        self.layout.addRow(self.ag_checkbox)

        self.framerate_label = QLabel("Frame Rate (fps):")
        self.framerate_spin = QDoubleSpinBox()
        self.framerate_spin.setDecimals(1)
        self.framerate_spin.setEnabled(False)
        self.framerate_spin.valueChanged.connect(self._on_framerate_changed)
        self.layout.addRow(self.framerate_label, self.framerate_spin)

        self.pf_label = QLabel("Pixel Format:")
        self.pf_combo = QComboBox()
        self.pf_combo.setEnabled(False)
        self.pf_combo.currentIndexChanged.connect(self._on_pf_changed)
        self.layout.addRow(self.pf_label, self.pf_combo)

    def set_recording_state(self, recording):
        self.is_recording = recording
        log.debug(f"CameraControlPanel: is_recording set to {self.is_recording}")

    def _setup_float_control(self, prop_id, spinbox, decimals=2, slider=None):
        log.info(f"CameraControlPanel: Looking for property {prop_id}")

        try:
            prop = self.grabber.device_property_map.find_float(prop_id)
            if not prop:
                log.warning(f"CameraControlPanel: Property {prop_id} not found.")
                return

            min_val = prop.minimum
            max_val = prop.maximum
            cur_val = prop.value
            step = 0.1  # Default fallback

            try:
                step = prop.increment
                if step <= 0:
                    raise ValueError()
            except Exception:
                step = (max_val - min_val) / 100.0

            spinbox.setRange(min_val, max_val)
            spinbox.setSingleStep(step)

            if step < 1.0:
                decimals = max(decimals, int(-math.floor(math.log10(step))) + 1)
            spinbox.setDecimals(min(decimals, 6))

            spinbox.setValue(cur_val)
            spinbox.setEnabled(True)

            scale = 1
            if slider is not None:
                digits = spinbox.decimals()
                scale = 10**digits
                slider.setRange(int(min_val * scale), int(max_val * scale))
                slider.setSingleStep(max(1, int(step * scale)))
                slider.setValue(int(cur_val * scale))
                slider.setEnabled(True)

            log.debug(
                f"{prop_id}: min={min_val}, max={max_val}, step={step}, value={cur_val}, unit={prop.unit}"
            )

            return scale

        except Exception as e:
            log.warning(f"CameraControlPanel: Failed to setup {prop_id}: {e}")

        return 1

    def _on_grabber_ready(self):
        log.info("CameraControlPanel: _on_grabber_ready() called")

        if not self.grabber or not getattr(self.grabber, "is_device_open", False):
            log.error(
                "CameraControlPanel: _on_grabber_ready() called but grabber is not open."
            )
            return

        self._exp_scale = self._setup_float_control(
            "ExposureTime", self.exposure_spin, decimals=1, slider=self.exposure_slider
        )
        self._gain_scale = self._setup_float_control(
            "Gain", self.gain_spin, decimals=2, slider=self.gain_slider
        )

        try:
            ae_node = self.grabber.device_property_map.find_enumeration("ExposureAuto")
            self.ae_checkbox.setChecked(ae_node.value == "Continuous")
            self.ae_checkbox.setEnabled(True)
        except Exception as e:
            log.warning(f"CameraControlPanel: Failed to init ExposureAuto: {e}")

        try:
            ag_node = self.grabber.device_property_map.find_enumeration("GainAuto")
            self.ag_checkbox.setChecked(ag_node.value == "Continuous")
            self.ag_checkbox.setEnabled(True)
        except Exception as e:
            log.warning(f"CameraControlPanel: Failed to init GainAuto: {e}")

        try:
            fr_node = self.grabber.device_property_map.find_float(
                "AcquisitionFrameRate"
            )
            self.framerate_spin.setRange(fr_node.minimum, fr_node.maximum)
            self.framerate_spin.setSingleStep(fr_node.increment or 0.1)
            self.framerate_spin.setValue(fr_node.value)  # ✅ CORRECT
            self.framerate_spin.setEnabled(True)
        except Exception as e:
            log.warning(f"CameraControlPanel: Failed to init AcquisitionFrameRate: {e}")

        try:
            pf_node = self.grabber.device_property_map.find_enumeration("PixelFormat")
            self.pf_combo.clear()
            for entry in pf_node.entries:
                self.pf_combo.addItem(entry.name)
            current = pf_node.value
            if current:
                idx = self.pf_combo.findText(current)
                if idx >= 0:
                    self.pf_combo.setCurrentIndex(idx)
            self.pf_combo.setEnabled(True)
        except Exception as e:
            log.warning(f"CameraControlPanel: Failed to init PixelFormat: {e}")

    def _on_exposure_changed(self, new_val):
        if self.is_recording:
            log.warning("Blocked Exposure change during recording")
            return
        try:
            node = self.grabber.device_property_map.find_float("ExposureTime")
            node.value = float(new_val)  # ✅ CORRECT WAY TO SET
            self.exposure_slider.blockSignals(True)
            self.exposure_slider.setValue(int(float(new_val) * self._exp_scale))
            self.exposure_slider.blockSignals(False)
        except Exception as e:
            log.error(
                f"CameraControlPanel: failed to set ExposureTime = {new_val}: {e}"
            )

    def _on_gain_changed(self, new_val):
        if self.is_recording:
            log.warning("Blocked Gain change during recording")
            return
        try:
            node = self.grabber.device_property_map.find_float("Gain")
            node.value = float(new_val)  # ✅ CORRECT
            self.gain_slider.blockSignals(True)
            self.gain_slider.setValue(int(float(new_val) * self._gain_scale))
            self.gain_slider.blockSignals(False)
        except Exception as e:
            log.error(f"CameraControlPanel: failed to set Gain = {new_val}: {e}")

    def _on_auto_exposure_toggled(self, state):
        if self.is_recording:
            log.warning("Blocked Auto Exposure toggle during recording")
            return
        try:
            node = self.grabber.device_property_map.find_enumeration("ExposureAuto")
            node.value = "Continuous" if state == Qt.Checked else "Off"
        except Exception as e:
            log.error(f"CameraControlPanel: failed to set ExposureAuto: {e}")

    def _on_auto_gain_toggled(self, state):
        if self.is_recording:
            log.warning("Blocked Auto Gain toggle during recording")
            return
        try:
            node = self.grabber.device_property_map.find_enumeration("GainAuto")
            node.value = "Continuous" if state == Qt.Checked else "Off"
        except Exception as e:
            log.error(f"CameraControlPanel: failed to set GainAuto: {e}")

    def _on_framerate_changed(self, new_val):
        if self.is_recording:
            log.warning("Blocked Frame Rate change during recording")
            return
        try:
            node = self.grabber.device_property_map.find_float("AcquisitionFrameRate")
            node.value = float(new_val)  # ✅ FIXED
        except Exception as e:
            log.error(
                f"CameraControlPanel: failed to set AcquisitionFrameRate = {new_val}: {e}"
            )

    def _on_pf_changed(self, index):
        if self.is_recording:
            log.warning("Blocked Pixel Format change during recording")
            return
        try:
            node = self.grabber.device_property_map.find_enumeration("PixelFormat")
            new_pf = self.pf_combo.currentText()
            if new_pf:
                node.value = new_pf
        except Exception as e:
            log.error(
                f"CameraControlPanel: failed to set PixelFormat = {self.pf_combo.currentText()}: {e}"
            )
