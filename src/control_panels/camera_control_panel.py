import logging

from PyQt5.QtWidgets import (
    QGroupBox,
    QWidget,
    QTabWidget,
    QFormLayout,
    QHBoxLayout,
    QVBoxLayout,
    QComboBox,
    QSlider,
    QLabel,
    QCheckBox,
    QSpinBox,
    QPushButton,
    QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtMultimedia import QCameraInfo

from config import DEFAULT_CAMERA_INDEX, DEFAULT_FRAME_SIZE

log = logging.getLogger(__name__)


class CameraControlPanel(QGroupBox):
    camera_selected = pyqtSignal(int, str)
    resolution_selected = pyqtSignal(str)
    exposure_changed = pyqtSignal(int)
    gain_changed = pyqtSignal(int)
    brightness_changed = pyqtSignal(int)
    auto_exposure_toggled = pyqtSignal(bool)
    roi_changed = pyqtSignal(int, int, int, int)
    roi_reset_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Camera", parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        tabs = QTabWidget()
        layout.addWidget(tabs)

        # Basic Controls
        basic = QWidget()
        basic_layout = QFormLayout(basic)
        self.cam_selector = QComboBox()
        self.cam_selector.setToolTip("Select camera")
        self.cam_selector.currentIndexChanged.connect(self._on_camera_selected)
        basic_layout.addRow("Device:", self.cam_selector)

        self.res_selector = QComboBox()
        self.res_selector.setToolTip("Select resolution")
        self.res_selector.currentIndexChanged.connect(self._on_resolution_selected)
        self.res_selector.setEnabled(False)
        basic_layout.addRow("Resolution:", self.res_selector)
        tabs.addTab(basic, "Basic")

        # Adjustments
        adj = QWidget()
        adj_layout = QFormLayout(adj)
        self.exposure_slider = QSlider(Qt.Horizontal)
        self.exposure_label = QLabel("N/A")
        exp_box = QHBoxLayout()
        exp_box.addWidget(self.exposure_slider)
        exp_box.addWidget(self.exposure_label)
        adj_layout.addRow("Exposure (µs):", exp_box)

        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_label = QLabel("N/A")
        gain_box = QHBoxLayout()
        gain_box.addWidget(self.gain_slider)
        gain_box.addWidget(self.gain_label)
        adj_layout.addRow("Gain (dB):", gain_box)

        self.brightness_slider = QSlider(Qt.Horizontal)
        self.brightness_label = QLabel("N/A")
        bright_box = QHBoxLayout()
        bright_box.addWidget(self.brightness_slider)
        bright_box.addWidget(self.brightness_label)
        adj_layout.addRow("Brightness:", bright_box)

        self.auto_exposure_cb = QCheckBox("Auto Exposure")
        adj_layout.addRow(self.auto_exposure_cb)
        tabs.addTab(adj, "Adjustments")

        # ROI
        roi = QWidget()
        roi_layout = QFormLayout(roi)
        self.roi_x = QSpinBox()
        self.roi_y = QSpinBox()
        self.roi_w = QSpinBox()
        self.roi_h = QSpinBox()
        for spin in (self.roi_x, self.roi_y, self.roi_w, self.roi_h):
            spin.setRange(0, max(DEFAULT_FRAME_SIZE) * 2)
        roi_layout.addRow("X:", self.roi_x)
        roi_layout.addRow("Y:", self.roi_y)
        roi_layout.addRow("Width:", self.roi_w)
        roi_layout.addRow("Height:", self.roi_h)
        self.reset_roi_btn = QPushButton("Reset ROI")
        roi_layout.addRow(self.reset_roi_btn)
        tabs.addTab(roi, "ROI")

        # Initialize controls disabled
        for widget in (
            self.exposure_slider,
            self.gain_slider,
            self.brightness_slider,
            self.auto_exposure_cb,
            roi,
        ):
            widget.setEnabled(False)

        # Connect adjustment signals
        self.exposure_slider.valueChanged.connect(self.exposure_changed)
        self.gain_slider.valueChanged.connect(self.gain_changed)
        self.brightness_slider.valueChanged.connect(self.brightness_changed)
        self.auto_exposure_cb.toggled.connect(self.auto_exposure_toggled)
        self.roi_x.valueChanged.connect(self._emit_roi)
        self.roi_y.valueChanged.connect(self._emit_roi)
        self.roi_w.valueChanged.connect(self._emit_roi)
        self.roi_h.valueChanged.connect(self._emit_roi)
        self.reset_roi_btn.clicked.connect(self.roi_reset_requested)

        self.populate_cameras()

    def populate_cameras(self):
        prev = self.cam_selector.currentData() or {}
        self.cam_selector.blockSignals(True)
        self.cam_selector.clear()
        cams = QCameraInfo.availableCameras()
        for i, info in enumerate(cams):
            desc = info.description() or f"Camera {i}"
            self.cam_selector.addItem(desc, {"id": i, "description": desc})
        if not cams:
            self.cam_selector.addItem("No cameras", {"id": -1, "description": ""})
            self.cam_selector.setEnabled(False)
        else:
            self.cam_selector.setEnabled(True)
        self.cam_selector.blockSignals(False)
        idx = 0
        if prev.get("id", -1) >= 0:
            for i in range(self.cam_selector.count()):
                if self.cam_selector.itemData(i)["id"] == prev["id"]:
                    idx = i
                    break
        elif DEFAULT_CAMERA_INDEX < self.cam_selector.count():
            idx = DEFAULT_CAMERA_INDEX
        self.cam_selector.setCurrentIndex(idx)
        self._on_camera_selected(idx)

    def _on_camera_selected(self, index):
        data = self.cam_selector.itemData(index) or {}
        cam_id = data.get("id", -1)
        desc = data.get("description", "")
        self.camera_selected.emit(cam_id, desc)
        self.res_selector.clear()
        self.res_selector.setEnabled(False)

    def _on_resolution_selected(self, index):
        res = self.res_selector.itemData(index)
        if res:
            self.resolution_selected.emit(res)

    def update_resolutions(self, modes):
        cur = self.res_selector.currentText()
        self.res_selector.blockSignals(True)
        self.res_selector.clear()
        if modes:
            for m in modes:
                self.res_selector.addItem(m, m)
            idx = self.res_selector.findText(cur)
            if idx < 0:
                default = f"{DEFAULT_FRAME_SIZE[0]}x{DEFAULT_FRAME_SIZE[1]}"
                idx = self.res_selector.findText(default) or 0
            self.res_selector.setCurrentIndex(idx)
            self.res_selector.setEnabled(True)
        else:
            self.res_selector.addItem("N/A", None)
            self.res_selector.setEnabled(False)
        self.res_selector.blockSignals(False)

    def update_control_from_properties(self, name, props):
        mapping = {
            "exposure": (
                self.exposure_slider,
                self.exposure_label,
                self.auto_exposure_cb,
            ),
            "gain": (self.gain_slider, self.gain_label, None),
            "brightness": (self.brightness_slider, self.brightness_label, None),
        }
        slider, label, checkbox = mapping.get(name, (None, None, None))
        enabled = props.get("enabled", False)
        if slider:
            slider.setEnabled(enabled)
            if enabled:
                slider.blockSignals(True)
                slider.setRange(int(props.get("min", 0)), int(props.get("max", 0)))
                slider.setValue(int(props.get("value", 0)))
                slider.blockSignals(False)
            label.setText(f"{props.get('value', 0):.1f}" if enabled else "N/A")
        if checkbox:
            checkbox.setEnabled(enabled)
            checkbox.blockSignals(True)
            checkbox.setChecked(props.get("is_auto_on", False))
            checkbox.blockSignals(False)
            if slider:
                slider.setEnabled(enabled and not checkbox.isChecked())

    def update_roi_controls(self, roi):
        tab = self.findChild(QTabWidget).widget(2)
        enabled = roi.get("max_w", 0) > 0 and roi.get("max_h", 0) > 0
        tab.setEnabled(enabled)
        for spin, key in zip(
            (self.roi_x, self.roi_y, self.roi_w, self.roi_h), ("x", "y", "w", "h")
        ):
            spin.blockSignals(True)
            spin.setRange(0, roi.get(f"max_{key}", 0))
            spin.setValue(roi.get(key, 0))
            spin.blockSignals(False)

    def _emit_roi(self):
        self.roi_changed.emit(
            self.roi_x.value(),
            self.roi_y.value(),
            self.roi_w.value(),
            self.roi_h.value(),
        )
