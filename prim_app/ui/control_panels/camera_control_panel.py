# PRIM-QTAPP/ui/control_panels/camera_control_panel.py
import logging
from PyQt5.QtWidgets import (
    QWidget,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QSlider,
    QCheckBox,
)
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot

log = logging.getLogger(__name__)


class CameraControlPanel(QWidget):
    property_changed = pyqtSignal(str, float)  # e.g., ('Gain', 0.5)
    auto_exposure_toggled = pyqtSignal(bool)

    def __init__(self, ic4_controller=None, parent=None):
        super().__init__(parent)
        self.ic4 = ic4_controller
        self._is_auto_exposure = True
        self._block_slider_signals = False
        self._build_ui()
        self._connect_signals()

        if self.ic4:
            self._sync_from_camera()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # --- Auto Exposure Toggle ---
        ae_row = QHBoxLayout()
        self.ae_checkbox = QCheckBox("Auto Exposure")
        self.ae_checkbox.setChecked(True)
        ae_row.addWidget(self.ae_checkbox)
        layout.addLayout(ae_row)

        # --- Gain Slider ---
        gain_row = QHBoxLayout()
        self.gain_label = QLabel("Gain:")
        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setMinimum(0)
        self.gain_slider.setMaximum(100)
        self.gain_slider.setEnabled(False)
        gain_row.addWidget(self.gain_label)
        gain_row.addWidget(self.gain_slider)
        layout.addLayout(gain_row)

        # --- Brightness Slider ---
        bright_row = QHBoxLayout()
        self.brightness_label = QLabel("Brightness:")
        self.brightness_slider = QSlider(Qt.Horizontal)
        self.brightness_slider.setMinimum(0)
        self.brightness_slider.setMaximum(100)
        self.brightness_slider.setEnabled(False)
        bright_row.addWidget(self.brightness_label)
        bright_row.addWidget(self.brightness_slider)
        layout.addLayout(bright_row)

        self.setLayout(layout)

    def _connect_signals(self):
        self.ae_checkbox.toggled.connect(self._on_auto_exposure_toggled)
        self.gain_slider.valueChanged.connect(self._on_gain_changed)
        self.brightness_slider.valueChanged.connect(self._on_brightness_changed)

    def _sync_from_camera(self):
        log.info("[CameraControlPanel] Syncing UI with current camera state...")
        if not self.ic4:
            log.warning("[CameraControlPanel] No IC4 controller attached.")
            return

        try:
            ae_on = self.ic4.get_auto_exposure()
            self._is_auto_exposure = ae_on
            self.ae_checkbox.setChecked(ae_on)
            self.gain_slider.setEnabled(not ae_on)
            self.brightness_slider.setEnabled(not ae_on)

            gain_range = self.ic4.get_property_range("Gain")
            gain_value = self.ic4.get_property("Gain")
            bright_range = self.ic4.get_property_range("Brightness")
            bright_value = self.ic4.get_property("Brightness")

            self._block_slider_signals = True
            self.gain_slider.setMinimum(gain_range[0])
            self.gain_slider.setMaximum(gain_range[1])
            self.gain_slider.setValue(int(gain_value))

            self.brightness_slider.setMinimum(bright_range[0])
            self.brightness_slider.setMaximum(bright_range[1])
            self.brightness_slider.setValue(int(bright_value))
            self._block_slider_signals = False

            log.info(
                "[CameraControlPanel] UI synced to Gain %.1f, Brightness %.1f",
                gain_value,
                bright_value,
            )

        except Exception as e:
            log.exception("[CameraControlPanel] Error syncing camera properties: %s", e)

    @pyqtSlot(bool)
    def _on_auto_exposure_toggled(self, checked):
        self._is_auto_exposure = checked
        if self.ic4:
            self.ic4.set_auto_exposure(checked)
        self.gain_slider.setEnabled(not checked)
        self.brightness_slider.setEnabled(not checked)
        log.info("[CameraControlPanel] Auto Exposure set to %s", checked)

    def _on_gain_changed(self, value):
        if self._block_slider_signals:
            return
        if self.ic4:
            self.ic4.set_property("Gain", float(value))
        self.property_changed.emit("Gain", float(value))

    def _on_brightness_changed(self, value):
        if self._block_slider_signals:
            return
        if self.ic4:
            self.ic4.set_property("Brightness", float(value))
        self.property_changed.emit("Brightness", float(value))

    def refresh_controls(self):
        self._sync_from_camera()

    def setEnabled(self, enabled: bool):
        super().setEnabled(enabled)
        self.ae_checkbox.setEnabled(enabled)
        self.gain_slider.setEnabled(enabled and not self._is_auto_exposure)
        self.brightness_slider.setEnabled(enabled and not self._is_auto_exposure)

    def update_controls_from_camera(self):
        self._sync_from_camera()
