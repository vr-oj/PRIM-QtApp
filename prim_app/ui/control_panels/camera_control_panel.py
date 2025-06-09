# camera_control_panel.py

import logging

from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtWidgets import (
    QWidget,
    QFormLayout,
    QLabel,
    QDoubleSpinBox,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
)

log = logging.getLogger(__name__)


class CameraControlPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.grabber = None
        self.is_recording = False

        # ───– Build the Qt widgets (all disabled by default) –────────────────
        self.layout = QFormLayout(self)
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.layout.setSpacing(6)

        # 1) Exposure Time (float)
        self.exposure_label = QLabel("Exposure (µs):")
        self.exposure_spin = QDoubleSpinBox()
        self.exposure_spin.setDecimals(1)
        self.exposure_spin.setSuffix(" µs")
        self.exposure_spin.setRange(0.0, 1e6)
        self.exposure_spin.setSingleStep(1000.0)
        self.exposure_spin.setEnabled(False)
        self.exposure_spin.valueChanged.connect(self._on_exposure_changed)
        self.layout.addRow(self.exposure_label, self.exposure_spin)

        # 2) Gain (float)
        self.gain_label = QLabel("Gain:")
        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setDecimals(2)
        self.gain_spin.setRange(0.0, 20.0)
        self.gain_spin.setSingleStep(0.1)
        self.gain_spin.setEnabled(False)
        self.gain_spin.valueChanged.connect(self._on_gain_changed)
        self.layout.addRow(self.gain_label, self.gain_spin)

        # 3) Auto-Exposure checkbox
        self.ae_checkbox = QCheckBox("Auto Exposure")
        self.ae_checkbox.setEnabled(False)
        self.ae_checkbox.stateChanged.connect(self._on_auto_exposure_toggled)
        self.layout.addRow(self.ae_checkbox)

        # 4) Auto-Gain checkbox
        self.ag_checkbox = QCheckBox("Auto Gain")
        self.ag_checkbox.setEnabled(False)
        self.ag_checkbox.stateChanged.connect(self._on_auto_gain_toggled)
        self.layout.addRow(self.ag_checkbox)

        # 5) Frame Rate (float)
        self.framerate_label = QLabel("Frame Rate (fps):")
        self.framerate_spin = QDoubleSpinBox()
        self.framerate_spin.setDecimals(1)
        self.framerate_spin.setRange(0.1, 120.0)
        self.framerate_spin.setSingleStep(0.5)
        self.framerate_spin.setEnabled(False)
        self.framerate_spin.valueChanged.connect(self._on_framerate_changed)
        self.layout.addRow(self.framerate_label, self.framerate_spin)

        # 6) Pixel Format dropdown (enum)
        self.pf_label = QLabel("Pixel Format:")
        self.pf_combo = QComboBox()
        self.pf_combo.setEnabled(False)
        self.pf_combo.currentIndexChanged.connect(self._on_pf_changed)
        self.layout.addRow(self.pf_label, self.pf_combo)

    def set_recording_state(self, recording):
        self.is_recording = recording
        log.debug(f"CameraControlPanel: is_recording set to {self.is_recording}")

    def _on_exposure_changed(self, new_val):
        if self.is_recording:
            log.warning("Blocked Exposure change during recording")
            return
        try:
            exp_node = self.grabber.device_property_map.find_float("ExposureTime")
            if exp_node:
                exp_node.value = float(new_val)
        except Exception as e:
            log.error(f"CameraControlPanel: failed to set ExposureTime = {new_val}: {e}")

    def _on_gain_changed(self, new_val):
        if self.is_recording:
            log.warning("Blocked Gain change during recording")
            return
        try:
            gain_node = self.grabber.device_property_map.find_float("Gain")
            if gain_node:
                gain_node.value = float(new_val)
        except Exception as e:
            log.error(f"CameraControlPanel: failed to set Gain = {new_val}: {e}")

    def _on_auto_exposure_toggled(self, state):
        if self.is_recording:
            log.warning("Blocked Auto Exposure toggle during recording")
            return
        try:
            ae_node = self.grabber.device_property_map.find_enumeration("ExposureAuto")
            if ae_node:
                ae_node.value = "Continuous" if state == Qt.Checked else "Off"
        except Exception as e:
            log.error(f"CameraControlPanel: failed to set ExposureAuto: {e}")

    def _on_auto_gain_toggled(self, state):
        if self.is_recording:
            log.warning("Blocked Auto Gain toggle during recording")
            return
        try:
            ag_node = self.grabber.device_property_map.find_enumeration("GainAuto")
            if ag_node:
                ag_node.value = "Continuous" if state == Qt.Checked else "Off"
        except Exception as e:
            log.error(f"CameraControlPanel: failed to set GainAuto: {e}")

    def _on_framerate_changed(self, new_val):
        if self.is_recording:
            log.warning("Blocked Frame Rate change during recording")
            return
        try:
            fr_node = self.grabber.device_property_map.find_float("AcquisitionFrameRate")
            if fr_node:
                fr_node.value = float(new_val)
        except Exception as e:
            log.error(f"CameraControlPanel: failed to set AcquisitionFrameRate = {new_val}: {e}")

    def _on_pf_changed(self, index):
        if self.is_recording:
            log.warning("Blocked Pixel Format change during recording")
            return
        try:
            pf_node = self.grabber.device_property_map.find_enumeration("PixelFormat")
            if pf_node:
                new_pf = self.pf_combo.currentText()
                if new_pf:
                    pf_node.value = new_pf
                else:
                    log.error("PixelFormat was empty; skipping property write")
        except Exception as e:
            log.error(f"CameraControlPanel: failed to set PixelFormat = {self.pf_combo.currentText()}: {e}")
