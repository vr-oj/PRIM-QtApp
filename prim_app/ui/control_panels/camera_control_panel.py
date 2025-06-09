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
)

from imagingcontrol4 import IC4Exception

log = logging.getLogger(__name__)


class CameraControlPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.grabber = None
        self.is_recording = False

        self.layout = QFormLayout(self)
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.layout.setSpacing(6)

        self.exposure_label = QLabel("Exposure (µs):")
        self.exposure_spin = QDoubleSpinBox()
        self.exposure_spin.setDecimals(1)
        self.exposure_spin.setSuffix(" µs")
        self.exposure_spin.setEnabled(False)
        self.exposure_spin.valueChanged.connect(self._on_exposure_changed)
        self.layout.addRow(self.exposure_label, self.exposure_spin)

        self.gain_label = QLabel("Gain:")
        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setDecimals(2)
        self.gain_spin.setEnabled(False)
        self.gain_spin.valueChanged.connect(self._on_gain_changed)
        self.layout.addRow(self.gain_label, self.gain_spin)

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

    def _setup_float_control(self, prop_id, spinbox, decimals=2):
        log.info(f"CameraControlPanel: Looking for property {prop_id}")

        try:
            prop = self.grabber.device_property_map.find_float(prop_id)
            if not prop:
                log.warning(f"CameraControlPanel: Property {prop_id} not found.")
                return

            min_val = prop.range_min
            max_val = prop.range_max
            cur_val = prop.get_value()

            try:
                step = prop.inc
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

            log.debug(
                f"{prop_id}: min={min_val}, max={max_val}, step={step}, value={cur_val}"
            )

        except Exception as e:
            log.warning(f"CameraControlPanel: Failed to setup {prop_id}: {e}")

    def _on_grabber_ready(self):
        log.info("CameraControlPanel: _on_grabber_ready() called")

        if not self.grabber or not getattr(self.grabber, "is_device_open", False):
            log.error(
                "CameraControlPanel: _on_grabber_ready() called but grabber is not open."
            )
            return

        self._setup_float_control("ExposureTime", self.exposure_spin, decimals=1)
        self._setup_float_control("Gain", self.gain_spin, decimals=2)

        log.info("Available float properties:")
        for prop in self.grabber.device_property_map.floats:
            try:
                log.info(f" - {prop.get_id().name}")
            except Exception as e:
                log.warning(f" - failed to get property name: {e}")

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
            self.framerate_spin.setValue(fr_node.get_value())
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
            node.set_value(float(new_val))
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
            node.set_value(float(new_val))
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
            node.set_value(float(new_val))
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
