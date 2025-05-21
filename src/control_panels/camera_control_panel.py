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
    QCheckBox,
    QLabel,
    QSizePolicy,
    QDoubleSpinBox,
)
from PyQt5.QtCore import Qt, pyqtSignal, QVariant, pyqtSlot

# IC4‐SDK flags
_IC4_AVAILABLE = False
_IC4_INITIALIZED = False
_ic4_module = None

try:
    import sys, os

    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.dirname(current_file_dir)
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    import prim_app

    _IC4_AVAILABLE = getattr(prim_app, "IC4_AVAILABLE", False)
    _IC4_INITIALIZED = getattr(prim_app, "IC4_INITIALIZED", False)
    if _IC4_INITIALIZED:
        # if prim_app exposed its ic4 module, use it; otherwise import directly
        _ic4_module = getattr(prim_app, "ic4_library_module", None) or __import__(
            "imagingcontrol4"
        )
    logging.getLogger(__name__).info(
        f"Checked prim_app for IC4 flags. AVAILABLE: {_IC4_AVAILABLE}, INITIALIZED: {_IC4_INITIALIZED}"
    )
except Exception as e:
    logging.getLogger(__name__).warning(f"IC4 check failed: {e}")

from config import DEFAULT_FRAME_SIZE

log = logging.getLogger(__name__)


class CameraControlPanel(QGroupBox):
    camera_selected = pyqtSignal(object)
    resolution_selected = pyqtSignal(str)
    exposure_changed = pyqtSignal(int)  # microseconds
    gain_changed = pyqtSignal(float)  # dB
    auto_exposure_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__("Camera Controls", parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # — Source tab —
        basic_tab = QWidget()
        basic_layout = QFormLayout(basic_tab)
        self.cam_selector = QComboBox()
        self.cam_selector.setToolTip("Select camera device")
        self.cam_selector.currentIndexChanged.connect(self._on_camera_selection_changed)
        basic_layout.addRow("Device:", self.cam_selector)

        self.res_selector = QComboBox()
        self.res_selector.setToolTip("Select camera resolution and format")
        self.res_selector.currentIndexChanged.connect(
            self._on_resolution_selection_changed
        )
        self.res_selector.setEnabled(False)
        basic_layout.addRow("Resolution:", self.res_selector)

        # ↓ add a status‐label
        self.current_res_label = QLabel("––")
        basic_layout.addRow("Current:", self.current_res_label)

        self.tabs.addTab(basic_tab, "Source")

        # — Adjustments tab —
        adj_tab = QWidget()
        adj_layout = QFormLayout(adj_tab)

        # Exposure (now in ms)
        self.exposure_ms_box = QDoubleSpinBox()
        self.exposure_ms_box.setDecimals(1)
        self.exposure_ms_box.setRange(0.1, 10000.0)  # fallback range in ms
        self.exposure_ms_box.setSuffix(" ms")
        self.exposure_ms_box.setKeyboardTracking(False)
        adj_layout.addRow("Exposure:", self.exposure_ms_box)

        self.auto_exposure_cb = QCheckBox("Auto Exposure")
        adj_layout.addRow(self.auto_exposure_cb)

        # Gain
        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_spinbox = QDoubleSpinBox()
        self.gain_spinbox.setDecimals(1)
        self.gain_spinbox.setKeyboardTracking(False)
        gain_box = QHBoxLayout()
        gain_box.addWidget(self.gain_slider)
        gain_box.addWidget(self.gain_spinbox)
        adj_layout.addRow("Gain (dB):", gain_box)

        self.tabs.addTab(adj_tab, "Adjustments")
        adj_tab.setEnabled(False)

        # — wire up controls —
        self.exposure_ms_box.editingFinished.connect(self._on_exposure_ms_entered)
        self.auto_exposure_cb.toggled.connect(self._on_auto_exposure_toggled)
        self.gain_slider.valueChanged.connect(self._on_gain_slider_changed)
        self.gain_spinbox.valueChanged.connect(self._on_gain_spinbox_changed)

        # initial populate
        self.populate_camera_list()
        self.disable_all_controls()

    def populate_camera_list(self):
        """Fill the camera combo via the IC4 device enumeration."""
        self.cam_selector.blockSignals(True)
        self.cam_selector.clear()
        self.cam_selector.addItem("Select Camera...", QVariant())

        if _IC4_INITIALIZED and _ic4_module:
            try:
                devices = _ic4_module.DeviceEnum.devices()
                if devices:
                    log.info(f"Found {len(devices)} TIS camera(s).")
                    for dev in devices:
                        text = f"{dev.model_name} (S/N: {dev.serial})"
                        self.cam_selector.addItem(text, QVariant(dev))
                else:
                    self.cam_selector.addItem("No TIS cameras found", QVariant())
            except Exception as e:
                log.error(f"Failed to list cameras: {e}")
                self.cam_selector.addItem("Error listing cameras", QVariant())
        else:
            self.cam_selector.addItem("TIS SDK N/A", QVariant())

        self.cam_selector.setEnabled(self.cam_selector.count() > 1)
        self.cam_selector.blockSignals(False)
        # trigger initial change
        if self.cam_selector.currentIndex() >= 0:
            self._on_camera_selection_changed(self.cam_selector.currentIndex())

    @pyqtSlot(int)
    def _on_camera_selection_changed(self, idx):
        data = self.cam_selector.itemData(idx)
        dev = data.value() if isinstance(data, QVariant) else data
        if dev and _ic4_module and isinstance(dev, _ic4_module.DeviceInfo):
            log.info(f"Camera selected: {dev.model_name}")
            self.camera_selected.emit(dev)
        else:
            log.info("Camera selection: None")
            self.camera_selected.emit(None)
            self.disable_all_controls()

    @pyqtSlot(int)
    def _on_resolution_selection_changed(self, idx):
        data = self.res_selector.itemData(idx)
        res = data.value() if isinstance(data, QVariant) else data
        if isinstance(res, str):
            self.resolution_selected.emit(res)

    @pyqtSlot(list)
    def update_camera_resolutions_list(self, modes: list):
        """
        Slot to receive a list of resolution strings (e.g. "640x480 Mono8").
        Populates the resolution combo.
        """
        current = self.res_selector.currentData()
        self.res_selector.blockSignals(True)
        self.res_selector.clear()
        if modes:
            for m in modes:
                self.res_selector.addItem(m, QVariant(m))
            self.res_selector.setEnabled(True)
            # emit first selection so widget can pick up defaults
            self._on_resolution_selection_changed(self.res_selector.currentIndex())
        else:
            self.res_selector.addItem("N/A", QVariant())
            self.res_selector.setEnabled(False)
        self.res_selector.blockSignals(False)

    @pyqtSlot(dict)
    def update_camera_properties_ui(self, props):
        """
        Rebuild or partially update the Exposure/Gain controls
        based on the dict coming from the camera thread.
        """
        # 1) full rebuild on 'controls'
        if "controls" in props:
            controls = props["controls"]
            exp = controls.get("exposure", {})
            gain = controls.get("gain", {})

            # Exposure
            exp_enabled = exp.get("enabled", False)
            exp_auto = exp.get("is_auto_on", False)
            min_us = int(exp.get("min", 0))
            max_us = int(exp.get("max", 0))
            val_us = int(exp.get("value", min_us))

            # convert to ms
            min_ms = min_us / 1000.0
            max_ms = max_us / 1000.0
            val_ms = val_us / 1000.0

            self.auto_exposure_cb.setEnabled(exp.get("auto_available", False))
            self.auto_exposure_cb.setChecked(exp_auto)

            self.exposure_ms_box.blockSignals(True)
            self.exposure_ms_box.setRange(min_ms, max_ms)
            self.exposure_ms_box.setValue(val_ms)
            self.exposure_ms_box.setEnabled(exp_enabled and not exp_auto)
            self.exposure_ms_box.block
