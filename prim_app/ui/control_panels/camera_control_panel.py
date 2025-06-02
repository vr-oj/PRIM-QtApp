# prim_app/ui/control_panels/camera_control_panel.py

import logging
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider
from PyQt5.QtCore import Qt, pyqtSlot
import imagingcontrol4 as ic4

log = logging.getLogger(__name__)


class CameraControlPanel(QWidget):
    """
    Once an ic4.Grabber is open, enumerate a few float/integer properties
    (e.g. Gain, ExposureTime) and expose them as sliders/buttons here.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.grabber = None  # Will be set by MainWindow._on_grabber_ready
        self.layout = QVBoxLayout(self)

        # Placeholders for dynamic widgets
        self._gain_slider = None
        self._exposure_slider = None

    def _on_grabber_ready(self):
        """
        Called by MainWindow when grabber.device_open() has succeeded.
        Build dynamic controls now that self.grabber.device_property_map is valid.
        """
        if self.grabber is None:
            log.error("CameraControlPanel: called _on_grabber_ready with no grabber.")
            return

        prop_map = self.grabber.device_property_map

        # Enumerate all enumeration properties (just for debugging)
        try:
            all_enum_names = [p.name for p in prop_map.all if isinstance(p, ic4.PropEnumeration)]
            log.info(f"====== Available Enumeration Properties: {all_enum_names}")
        except Exception as e:
            log.error(f"Failed to list enumeration properties: {e}")

        # ─── Gain Slider ─────────────────────────────────
        gain_prop = prop_map.find_float("Gain")
        if gain_prop:
            try:
                minv = gain_prop.minimum
            except Exception:
                minv = 0.0
            try:
                maxv = gain_prop.maximum
            except Exception:
                maxv = 100.0
            try:
                step = gain_prop.increment
            except Exception:
                step = 1.0

            try:
                current = gain_prop.value
            except Exception:
                current = minv

            gain_layout = QHBoxLayout()
            gain_label = QLabel(f"Gain ({current:.1f}):", self)
            gain_slider = QSlider(Qt.Horizontal, self)
            gain_slider.setMinimum(int(minv))
            gain_slider.setMaximum(int(maxv))
            gain_slider.setSingleStep(int(step))
            gain_slider.setValue(int(current))
            gain_slider.valueChanged.connect(lambda v: self._on_gain_changed(v, gain_label))
            gain_layout.addWidget(gain_label)
            gain_layout.addWidget(gain_slider)
            self.layout.addLayout(gain_layout)
            self._gain_slider = gain_slider
        else:
            log.error("Failed to build Gain control: 'Gain' property not found or inaccessible.")

        # ─── Exposure Slider ─────────────────────────────
        exp_prop = prop_map.find_float("ExposureTime")
        if exp_prop:
            try:
                minv = exp_prop.minimum
            except Exception:
                minv = 0.0
            try:
                maxv = exp_prop.maximum
            except Exception:
                maxv = 100000.0
            try:
                step = exp_prop.increment
            except Exception:
                step = 1.0

            try:
                current = exp_prop.value
            except Exception:
                current = minv

            exp_layout = QHBoxLayout()
            exp_label = QLabel(f"Exposure ({current:.1f}):", self)
            exp_slider = QSlider(Qt.Horizontal, self)
            exp_slider.setMinimum(int(minv))
            exp_slider.setMaximum(int(maxv))
            exp_slider.setSingleStep(int(step))
            exp_slider.setValue(int(current))
            exp_slider.valueChanged.connect(lambda v: self._on_exposure_changed(v, exp_label))
            exp_layout.addWidget(exp_label)
            exp_layout.addWidget(exp_slider)
            self.layout.addLayout(exp_layout)
            self._exposure_slider = exp_slider
        else:
            log.error("Failed to build Exposure control: 'ExposureTime' not found or inaccessible.")

        # … you can replicate the same pattern for Brightness, Gamma, etc. …

    @pyqtSlot(int, QLabel)
    def _on_gain_changed(self, value: int, label: QLabel):
        """
        Called when user drags the Gain slider. Update both the camera and the label.
        """
        if not self.grabber:
            return
        try:
            gain_prop = self.grabber.device_property_map.find_float("Gain")
            gain_prop.value = float(value)
            label.setText(f"Gain ({value:.1f}):")
        except Exception as e:
            log.error(f"Failed to set Gain to {value}: {e}")

    @pyqtSlot(int, QLabel)
    def _on_exposure_changed(self, value: int, label: QLabel):
        """
        Called when user drags the Exposure slider. Update camera and label.
        """
        if not self.grabber:
            return
        try:
            exp_prop = self.grabber.device_property_map.find_float("ExposureTime")
            exp_prop.value = float(value)
            label.setText(f"Exposure ({value:.1f}):")
        except Exception as e:
            log.error(f"Failed to set ExposureTime to {value}: {e}")