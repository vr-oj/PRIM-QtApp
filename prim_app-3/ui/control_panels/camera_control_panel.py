import logging
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QFormLayout,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QTabWidget,
    QGroupBox,
    QHBoxLayout,
)
from PyQt5.QtCore import pyqtSignal

log = logging.getLogger(__name__)


class CameraControlPanel(QWidget):
    # Signal emitted when user changes a camera setting
    camera_setting_changed = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.device_model = None
        self.controls = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout()
        self.tabs = QTabWidget()

        self.info_tab = QWidget()
        self.settings_tab = QWidget()

        self._build_info_tab()
        self._build_settings_tab()

        self.tabs.addTab(self.info_tab, "Camera Info")
        self.tabs.addTab(self.settings_tab, "Adjust Settings")

        layout.addWidget(self.tabs)
        self.setLayout(layout)

    def _build_info_tab(self):
        layout = QFormLayout()

        self.label_model = QLabel("-")
        self.label_pixel_format = QLabel("-")
        self.label_resolution = QLabel("-")
        self.label_fps = QLabel("-")

        layout.addRow("Model:", self.label_model)
        layout.addRow("Pixel Format:", self.label_pixel_format)
        layout.addRow("Resolution:", self.label_resolution)
        layout.addRow("FPS:", self.label_fps)

        self.info_tab.setLayout(layout)

    def _build_settings_tab(self):
        layout = QVBoxLayout()
        form = QFormLayout()

        # Auto Exposure
        self.auto_exposure = QComboBox()
        self.auto_exposure.addItems(["Off", "Continuous"])
        self.auto_exposure.currentTextChanged.connect(
            lambda val: self._emit_change("ExposureAuto", val)
        )
        self.auto_exposure.currentTextChanged.connect(self._toggle_exposure_controls)
        form.addRow("Auto Exposure:", self.auto_exposure)
        self.controls["ExposureAuto"] = self.auto_exposure

        # Gain (adjustable if auto exposure is off)
        self.gain = QSpinBox()
        self.gain.setRange(0, 100)
        self.gain.setEnabled(False)
        self.gain.valueChanged.connect(lambda val: self._emit_change("Gain", val))
        form.addRow("Gain:", self.gain)
        self.controls["Gain"] = self.gain

        # Brightness
        self.brightness = QSpinBox()
        self.brightness.setRange(0, 255)
        self.brightness.setEnabled(False)
        self.brightness.valueChanged.connect(
            lambda val: self._emit_change("Brightness", val)
        )
        form.addRow("Brightness:", self.brightness)
        self.controls["Brightness"] = self.brightness

        # Resolution
        self.resolution = QComboBox()
        self.resolution.currentTextChanged.connect(
            lambda val: self._emit_change("Resolution", val)
        )
        form.addRow("Resolution:", self.resolution)
        self.controls["Resolution"] = self.resolution

        # FPS
        self.fps = QComboBox()
        self.fps.addItems(["15", "30", "60"])
        self.fps.currentTextChanged.connect(
            lambda val: self._emit_change("FPS", int(val))
        )
        form.addRow("FPS:", self.fps)
        self.controls["FPS"] = self.fps

        layout.addLayout(form)
        self.settings_tab.setLayout(layout)

    def _toggle_exposure_controls(self, mode):
        is_manual = mode == "Off"
        self.gain.setEnabled(is_manual)
        self.brightness.setEnabled(is_manual)

    def _emit_change(self, name, value):
        log.debug(f"[CameraControlPanel] User changed {name} -> {value}")
        self.camera_setting_changed.emit(name, value)

    def load_camera_info(self, model, pix_fmt, width, height, fps):
        self.device_model = model
        self.label_model.setText(model)
        self.label_pixel_format.setText(pix_fmt)
        self.label_resolution.setText(f"{width} × {height}")
        self.label_fps.setText(f"{fps:.1f} FPS")

        # Populate resolution list if known
        if model == "DMK 33UX250":
            res_list = [f"{w}×{h}" for w, h in [(2448, 2048), (1280, 1024), (640, 480)]]
        elif model == "DMK 33UP5000":
            res_list = [f"{w}×{h}" for w, h in [(2592, 2048), (1280, 720), (640, 480)]]
        else:
            res_list = ["640×480"]

        self.resolution.clear()
        self.resolution.addItems(res_list)
