# File: prim_app/ui/control_panels/camera_control_panel.py

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
    """
    A panel of camera controls (Exposure, Gain, Auto-settings, etc.).
    MainWindow will assign `self.grabber = <ic4.Grabber>` when the camera is open.
    Once `grabber_ready` fires, MainWindow calls `_on_grabber_ready()`, which should
    enumerate and enable any controls that actually exist on the device.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grabber = None

        # ───– Build the Qt widgets (all disabled by default) –────────────────
        self.layout = QFormLayout(self)
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.layout.setSpacing(6)

        # 1) Exposure Time (float)
        self.exposure_label = QLabel("Exposure (µs):")
        self.exposure_spin = QDoubleSpinBox()
        self.exposure_spin.setDecimals(1)
        self.exposure_spin.setSuffix(" µs")
        self.exposure_spin.setRange(0.0, 1e6)  # placeholder; will adjust later
        self.exposure_spin.setSingleStep(1000.0)
        self.exposure_spin.setEnabled(False)
        self.exposure_spin.valueChanged.connect(self._on_exposure_changed)
        self.layout.addRow(self.exposure_label, self.exposure_spin)

        # 2) Gain (float)
        self.gain_label = QLabel("Gain:")
        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setDecimals(2)
        self.gain_spin.setRange(0.0, 20.0)  # placeholder; will adjust later
        self.gain_spin.setSingleStep(0.1)
        self.gain_spin.setEnabled(False)
        self.gain_spin.valueChanged.connect(self._on_gain_changed)
        self.layout.addRow(self.gain_label, self.gain_spin)

        # 3) Auto-Exposure checkbox
        self.ae_checkbox = QCheckBox("Auto Exposure")
        self.ae_checkbox.setEnabled(False)
        self.ae_checkbox.stateChanged.connect(self._on_auto_exposure_toggled)
        self.layout.addRow(self.ae_checkbox)

        # 4) Auto-Gain checkbox (if available)
        self.ag_checkbox = QCheckBox("Auto Gain")
        self.ag_checkbox.setEnabled(False)
        self.ag_checkbox.stateChanged.connect(self._on_auto_gain_toggled)
        self.layout.addRow(self.ag_checkbox)

        # 5) Frame Rate (float) – optional
        self.framerate_label = QLabel("Frame Rate (fps):")
        self.framerate_spin = QDoubleSpinBox()
        self.framerate_spin.setDecimals(1)
        self.framerate_spin.setRange(0.1, 120.0)  # placeholder
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

        # (You can add more controls here—e.g. Gamma, White Balance, etc.—using the same pattern.)

    def _on_grabber_ready(self):
        """
        Called by MainWindow right after `grabber` is set. At this point:
          - self.grabber.device_property_map is valid.
          - We can safely query which nodes exist and populate our controls.
        """
        if self.grabber is None:
            return

        dm = self.grabber.device_property_map

        # ─── ExposureTime ─────────────────────────────────────────────────────
        try:
            exp_node = dm.find_float("ExposureTime")
            if exp_node:
                # If the PropFloat has .min and .max, use them to set ranges
                try:
                    amin = float(exp_node.min)
                    amax = float(exp_node.max)
                    self.exposure_spin.setRange(amin, amax)
                    self.exposure_spin.setSingleStep((amax - amin) / 100.0)
                except AttributeError:
                    # Some cameras don’t expose min/max – leave defaults
                    pass

                # Set current value
                self.exposure_spin.setValue(float(exp_node.value))
                self.exposure_spin.setEnabled(True)
            else:
                self.exposure_label.setText("Exposure (N/A)")
        except Exception as e:
            self.exposure_label.setText("Exposure (Error)")
            log.error(f"CameraControlPanel: could not query ExposureTime: {e}")

        # ─── Gain ──────────────────────────────────────────────────────────────
        try:
            gain_node = dm.find_float("Gain")
            if gain_node:
                try:
                    gmin = float(gain_node.min)
                    gmax = float(gain_node.max)
                    self.gain_spin.setRange(gmin, gmax)
                    self.gain_spin.setSingleStep((gmax - gmin) / 100.0)
                except AttributeError:
                    pass

                self.gain_spin.setValue(float(gain_node.value))
                self.gain_spin.setEnabled(True)
            else:
                self.gain_label.setText("Gain (N/A)")
        except Exception as e:
            self.gain_label.setText("Gain (Error)")
            log.error(f"CameraControlPanel: could not query Gain: {e}")

        # ─── Auto-Exposure ─────────────────────────────────────────────────────
        try:
            ae_node = dm.find_enumeration("ExposureAuto")
            if ae_node:
                # If enum value is "Continuous", check the box
                self.ae_checkbox.setChecked(ae_node.value == "Continuous")
                self.ae_checkbox.setEnabled(True)
            else:
                self.ae_checkbox.setText("Auto Exposure (N/A)")
        except Exception as e:
            self.ae_checkbox.setText("Auto Exposure (Error)")
            log.error(f"CameraControlPanel: could not query ExposureAuto: {e}")

        # ─── Auto-Gain ─────────────────────────────────────────────────────────
        try:
            ag_node = dm.find_enumeration("GainAuto")
            if ag_node:
                self.ag_checkbox.setChecked(ag_node.value == "Continuous")
                self.ag_checkbox.setEnabled(True)
            else:
                self.ag_checkbox.setText("Auto Gain (N/A)")
        except Exception as e:
            self.ag_checkbox.setText("Auto Gain (Error)")
            log.error(f"CameraControlPanel: could not query GainAuto: {e}")

        # ─── Frame Rate ────────────────────────────────────────────────────────
        try:
            fr_node = dm.find_float("AcquisitionFrameRate")
            if fr_node:
                try:
                    fmin = float(fr_node.min)
                    fmax = float(fr_node.max)
                    self.framerate_spin.setRange(fmin, fmax)
                    self.framerate_spin.setSingleStep((fmax - fmin) / 100.0)
                except AttributeError:
                    pass

                self.framerate_spin.setValue(float(fr_node.value))
                self.framerate_spin.setEnabled(True)
            else:
                self.framerate_label.setText("Frame Rate (N/A)")
        except Exception as e:
            self.framerate_label.setText("Frame Rate (Error)")
            log.error(f"CameraControlPanel: could not query AcquisitionFrameRate: {e}")

        # ─── Pixel Format ──────────────────────────────────────────────────────
        try:
            pf_node = dm.find_enumeration("PixelFormat")
            if pf_node:
                self.pf_combo.clear()
                # Build a list of all available PFs
                for entry in pf_node.entries:
                    if entry.is_available:
                        self.pf_combo.addItem(entry.name)
                # Select the current format
                current_pf = pf_node.value
                idx = self.pf_combo.findText(current_pf)
                if idx >= 0:
                    self.pf_combo.setCurrentIndex(idx)
                self.pf_combo.setEnabled(True)
            else:
                self.pf_label.setText("Pixel Format (N/A)")
        except Exception as e:
            self.pf_label.setText("Pixel Format (Error)")
            log.error(f"CameraControlPanel: could not query PixelFormat: {e}")

        # ─── (Add any additional nodes you want to expose here) ──────────────

    # ─── User‐driven slots: write back to the camera nodes ────────────────────

    @pyqtSlot(float)
    def _on_exposure_changed(self, new_val):
        try:
            exp_node = self.grabber.device_property_map.find_float("ExposureTime")
            if exp_node:
                exp_node.value = float(new_val)
        except Exception as e:
            log.error(
                f"CameraControlPanel: failed to set ExposureTime = {new_val}: {e}"
            )

    @pyqtSlot(float)
    def _on_gain_changed(self, new_val):
        try:
            gain_node = self.grabber.device_property_map.find_float("Gain")
            if gain_node:
                gain_node.value = float(new_val)
        except Exception as e:
            log.error(f"CameraControlPanel: failed to set Gain = {new_val}: {e}")

    @pyqtSlot(int)
    def _on_auto_exposure_toggled(self, state):
        try:
            ae_node = self.grabber.device_property_map.find_enumeration("ExposureAuto")
            if ae_node:
                ae_node.value = "Continuous" if state == Qt.Checked else "Off"
        except Exception as e:
            log.error(f"CameraControlPanel: failed to set ExposureAuto: {e}")

    @pyqtSlot(int)
    def _on_auto_gain_toggled(self, state):
        try:
            ag_node = self.grabber.device_property_map.find_enumeration("GainAuto")
            if ag_node:
                ag_node.value = "Continuous" if state == Qt.Checked else "Off"
        except Exception as e:
            log.error(f"CameraControlPanel: failed to set GainAuto: {e}")

    @pyqtSlot(float)
    def _on_framerate_changed(self, new_val):
        try:
            fr_node = self.grabber.device_property_map.find_float(
                "AcquisitionFrameRate"
            )
            if fr_node:
                fr_node.value = float(new_val)
        except Exception as e:
            log.error(
                f"CameraControlPanel: failed to set AcquisitionFrameRate = {new_val}: {e}"
            )

    @pyqtSlot(int)
    def _on_pf_changed(self, index):
        try:
            pf_node = self.grabber.device_property_map.find_enumeration("PixelFormat")
            if pf_node:
                new_pf = self.pf_combo.currentText()
                pf_node.value = new_pf
        except Exception as e:
            log.error(
                f"CameraControlPanel: failed to set PixelFormat = {self.pf_combo.currentText()}: {e}"
            )
