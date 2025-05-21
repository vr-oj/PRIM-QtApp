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
    QDoubleSpinBox,
)
from PyQt5.QtCore import Qt, pyqtSignal, QVariant, pyqtSlot

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
        if hasattr(prim_app, "ic4_library_module"):
            _ic4_module = prim_app.ic4_library_module
        else:
            import imagingcontrol4 as ic4_sdk

            _ic4_module = ic4_sdk
    logging.getLogger(__name__).info(
        f"Successfully checked prim_app for IC4 flags. AVAILABLE: {_IC4_AVAILABLE}, INITIALIZED: {_IC4_INITIALIZED}"
    )
except Exception as e:
    logging.getLogger(__name__).warning(f"IC4 check failed: {e}")

from config import DEFAULT_FRAME_SIZE

log = logging.getLogger(__name__)


class CameraControlPanel(QGroupBox):
    camera_selected = pyqtSignal(object)
    resolution_selected = pyqtSignal(str)
    exposure_changed = pyqtSignal(int)
    gain_changed = pyqtSignal(float)
    auto_exposure_toggled = pyqtSignal(bool)
    # ROI signals removed!

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
        self.tabs.addTab(basic_tab, "Source")

        # — Adjustments tab —
        adj_tab = QWidget()
        adj_layout = QFormLayout(adj_tab)

        # Exposure
        self.exposure_slider = QSlider(Qt.Horizontal)
        self.exposure_spinbox = QSpinBox()
        self.exposure_spinbox.setKeyboardTracking(False)
        exp_box = QHBoxLayout()
        exp_box.addWidget(self.exposure_slider)
        exp_box.addWidget(self.exposure_spinbox)
        adj_layout.addRow("Exposure (µs):", exp_box)
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

        # wire up adjustment controls
        self.exposure_slider.valueChanged.connect(self._on_exposure_slider_changed)
        self.exposure_spinbox.valueChanged.connect(self._on_exposure_spinbox_changed)
        self.auto_exposure_cb.toggled.connect(self._on_auto_exposure_toggled)

        self.gain_slider.valueChanged.connect(self._on_gain_slider_changed)
        self.gain_spinbox.valueChanged.connect(self._on_gain_spinbox_changed)

        # initial population
        self.populate_camera_list()
        self.disable_all_controls()

    def populate_camera_list(self):
        self.cam_selector.blockSignals(True)
        self.cam_selector.clear()
        self.cam_selector.addItem("Select Camera...", QVariant())

        if _IC4_INITIALIZED and _ic4_module:
            try:
                devices = _ic4_module.DeviceEnum.devices()
                if devices:
                    log.info(f"Found {len(devices)} TIS camera(s).")
                    for dev in devices:
                        text = f"TIS: {dev.model_name} (S/N: {dev.serial})"
                        self.cam_selector.addItem(text, QVariant(dev))
                else:
                    self.cam_selector.addItem("No TIS cameras found", QVariant())
            except Exception as e:
                log.error(f"Failed to list TIS cameras: {e}")
                self.cam_selector.addItem("Error listing cameras", QVariant())
        else:
            self.cam_selector.addItem("TIS SDK N/A", QVariant())

        self.cam_selector.setEnabled(self.cam_selector.count() > 1)
        self.cam_selector.blockSignals(False)
        if self.cam_selector.currentIndex() >= 0:
            self._on_camera_selection_changed(self.cam_selector.currentIndex())

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

    def _on_resolution_selection_changed(self, idx):
        data = self.res_selector.itemData(idx)
        res = data.value() if isinstance(data, QVariant) else data
        if isinstance(res, str):
            self.resolution_selected.emit(res)

    @pyqtSlot(list)
    def update_camera_resolutions_list(self, modes: list):
        """Fill resolution combo with List[str]"""
        current = self.res_selector.currentData()
        self.res_selector.blockSignals(True)
        self.res_selector.clear()
        if modes:
            for m in modes:
                self.res_selector.addItem(m, QVariant(m))
            # restore selection if possible
            if current:
                i = self.res_selector.findData(QVariant(current))
                if i >= 0:
                    self.res_selector.setCurrentIndex(i)
            self.res_selector.setEnabled(True)
            # emit first selection
            self._on_resolution_selection_changed(self.res_selector.currentIndex())
        else:
            self.res_selector.addItem("N/A", QVariant())
            self.res_selector.setEnabled(False)
        self.res_selector.blockSignals(False)

    # — New: put back this slot so MainWindow can connect to it —
    @pyqtSlot(dict)
    def update_camera_properties_ui(self, props: dict):
        """
        Enables/disables and updates the Exposure & Gain controls based on
        the 'controls' dict coming from the camera thread.
        """
        log.debug(f"CameraControlPanel updating UI from properties: {props}")
        controls = props.get("controls", {})

        # Exposure
        exp = controls.get("exposure", {})
        exp_enabled = exp.get("enabled", False)
        exp_auto = exp.get("is_auto_on", False)
        self.exposure_slider.blockSignals(True)
        self.exposure_spinbox.blockSignals(True)
        self.auto_exposure_cb.blockSignals(True)

        self.auto_exposure_cb.setEnabled(exp.get("auto_available", False))
        self.auto_exposure_cb.setChecked(exp_auto)

        if exp_enabled:
            min_e, max_e = int(exp.get("min", 0)), int(exp.get("max", 100000))
            val_e = int(exp.get("value", min_e))
            self.exposure_slider.setRange(min_e, max_e)
            self.exposure_slider.setValue(val_e)
            self.exposure_spinbox.setRange(min_e, max_e)
            self.exposure_spinbox.setValue(val_e)
        self.exposure_slider.setEnabled(exp_enabled and not exp_auto)
        self.exposure_spinbox.setEnabled(exp_enabled and not exp_auto)

        self.exposure_slider.blockSignals(False)
        self.exposure_spinbox.blockSignals(False)
        self.auto_exposure_cb.blockSignals(False)

        # Gain
        gain = controls.get("gain", {})
        gain_enabled = gain.get("enabled", False)
        self.gain_slider.blockSignals(True)
        self.gain_spinbox.blockSignals(True)

        if gain_enabled:
            min_g, max_g = float(gain.get("min", 0.0)), float(gain.get("max", 30.0))
            val_g = float(gain.get("value", min_g))
            self.gain_spinbox.setRange(min_g, max_g)
            self.gain_spinbox.setValue(val_g)

            # map float→slider
            s_min, s_max = self.gain_slider.minimum(), self.gain_slider.maximum()
            if s_max == s_min:
                self.gain_slider.setRange(0, 1000)
                s_min, s_max = 0, 1000
            pos = (
                int((val_g - min_g) / (max_g - min_g) * (s_max - s_min))
                if max_g > min_g
                else s_min
            )
            self.gain_slider.setValue(max(s_min, min(pos, s_max)))

        self.gain_slider.setEnabled(gain_enabled)
        self.gain_spinbox.setEnabled(gain_enabled)

        self.gain_slider.blockSignals(False)
        self.gain_spinbox.blockSignals(False)

        # Enable the Adjustments tab if either control is available
        self.tabs.widget(1).setEnabled(exp_enabled or gain_enabled)

    def _on_exposure_slider_changed(self, v):
        self.exposure_spinbox.blockSignals(True)
        self.exposure_spinbox.setValue(v)
        self.exposure_spinbox.blockSignals(False)
        self.exposure_changed.emit(v)

    def _on_exposure_spinbox_changed(self, v):
        self.exposure_slider.blockSignals(True)
        self.exposure_slider.setValue(v)
        self.exposure_slider.blockSignals(False)
        self.exposure_changed.emit(v)

    def _on_auto_exposure_toggled(self, chk):
        self.auto_exposure_toggled.emit(chk)

    def _on_gain_slider_changed(self, slider_val):
        min_v, max_v = self.gain_spinbox.minimum(), self.gain_spinbox.maximum()
        if max_v > min_v:
            val = min_v + (slider_val - self.gain_slider.minimum()) / (
                self.gain_slider.maximum() - self.gain_slider.minimum()
            ) * (max_v - min_v)
        else:
            val = min_v
        self.gain_spinbox.blockSignals(True)
        self.gain_spinbox.setValue(round(val, 1))
        self.gain_spinbox.blockSignals(False)
        self.gain_changed.emit(self.gain_spinbox.value())

    def _on_gain_spinbox_changed(self, v):
        smin, smax = self.gain_slider.minimum(), self.gain_slider.maximum()
        gmin, gmax = self.gain_spinbox.minimum(), self.gain_spinbox.maximum()
        if gmax > gmin:
            pos = int((v - gmin) / (gmax - gmin) * (smax - smin))
        else:
            pos = smin
        self.gain_slider.blockSignals(True)
        self.gain_slider.setValue(max(smin, min(pos, smax)))
        self.gain_slider.blockSignals(False)
        self.gain_changed.emit(v)

    def disable_all_controls(self):
        log.debug("CameraControlPanel: Disabling all controls.")
        # disable Adjustments tab and all its widgets
        self.tabs.widget(1).setEnabled(False)
        for w in (
            self.exposure_slider,
            self.exposure_spinbox,
            self.auto_exposure_cb,
            self.gain_slider,
            self.gain_spinbox,
        ):
            w.setEnabled(False)
            if hasattr(w, "setValue"):
                w.setValue(w.minimum())
        # reset resolution combo
        self.res_selector.blockSignals(True)
        self.res_selector.clear()
        self.res_selector.addItem("N/A", QVariant())
        self.res_selector.setEnabled(False)
        self.res_selector.blockSignals(False)
