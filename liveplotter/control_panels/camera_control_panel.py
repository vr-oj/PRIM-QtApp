# camera_control_panel.py

import logging
from PyQt5.QtWidgets import (
    QWidget,
    QLabel,
    QComboBox,
    QSlider,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QCheckBox,
    QFormLayout,
)
from PyQt5.QtCore import Qt, pyqtSignal

log = logging.getLogger(__name__)


class CameraControlPanel(QWidget):
    resolution_changed = pyqtSignal(str)
    fps_changed = pyqtSignal(float)
    auto_exposure_toggled = pyqtSignal(bool)
    gain_changed = pyqtSignal(int)
    brightness_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        tabs.addTab(self._create_format_tab(), "Format")
        tabs.addTab(self._create_exposure_tab(), "Exposure")
        tabs.addTab(self._create_gain_tab(), "Gain/Brightness")

        layout.addWidget(tabs)
        self.setLayout(layout)

    def _create_format_tab(self):
        widget = QWidget()
        form = QFormLayout()

        self.resolution_combo = QComboBox()
        self.resolution_combo.currentTextChanged.connect(self.resolution_changed.emit)
        form.addRow(QLabel("Resolution:"), self.resolution_combo)

        self.fps_combo = QComboBox()
        self.fps_combo.addItems(["15", "30", "60", "120"])
        self.fps_combo.currentTextChanged.connect(
            lambda val: self.fps_changed.emit(float(val))
        )
        form.addRow(QLabel("FPS:"), self.fps_combo)

        widget.setLayout(form)
        return widget

    def _create_exposure_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()

        self.auto_exposure_checkbox = QCheckBox("Auto Exposure")
        self.auto_exposure_checkbox.stateChanged.connect(
            lambda state: self.auto_exposure_toggled.emit(state == Qt.Checked)
        )
        layout.addWidget(self.auto_exposure_checkbox)
        layout.addStretch()
        widget.setLayout(layout)
        return widget

    def _create_gain_tab(self):
        widget = QWidget()
        form = QFormLayout()

        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setMinimum(0)
        self.gain_slider.setMaximum(100)
        self.gain_slider.valueChanged.connect(self.gain_changed.emit)
        form.addRow(QLabel("Gain:"), self.gain_slider)

        self.brightness_slider = QSlider(Qt.Horizontal)
        self.brightness_slider.setMinimum(0)
        self.brightness_slider.setMaximum(100)
        self.brightness_slider.valueChanged.connect(self.brightness_changed.emit)
        form.addRow(QLabel("Brightness:"), self.brightness_slider)

        widget.setLayout(form)
        return widget

    def update_resolutions(self, resolutions: list[str]):
        self.resolution_combo.clear()
        self.resolution_combo.addItems(resolutions)
