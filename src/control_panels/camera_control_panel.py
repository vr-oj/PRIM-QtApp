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
    import sys
    import os

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

except ImportError as e:
    logging.getLogger(__name__).warning(
        f"Could not import 'prim_app' module to check IC4 status: {e}. Assuming TIS SDK not available."
    )
except AttributeError as e:
    logging.getLogger(__name__).warning(
        f"'prim_app' module imported, but flags (IC4_AVAILABLE/IC4_INITIALIZED) are missing: {e}. Assuming TIS SDK not available."
    )
except Exception as e:
    logging.getLogger(__name__).error(
        f"Unexpected error during prim_app import for IC4 flags: {e}"
    )

from config import DEFAULT_FRAME_SIZE

log = logging.getLogger(__name__)


class CameraControlPanel(QGroupBox):
    camera_selected = pyqtSignal(object)
    resolution_selected = pyqtSignal(str)
    exposure_changed = pyqtSignal(int)
    gain_changed = pyqtSignal(float)
    auto_exposure_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__("Camera Controls", parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Source tab
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

        # Adjustments tab
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

        # Connect adjustment signals
        self.exposure_slider.valueChanged.connect(self._on_exposure_slider_changed)
        self.exposure_spinbox.valueChanged.connect(self._on_exposure_spinbox_changed)
        self.auto_exposure_cb.toggled.connect(self._on_auto_exposure_toggled)
        self.gain_slider.valueChanged.connect(self._on_gain_slider_changed)
        self.gain_spinbox.valueChanged.connect(self._on_gain_spinbox_changed)

        self.populate_camera_list()
        self.disable_all_controls()

    def populate_camera_list(self):
        self.cam_selector.blockSignals(True)
        self.cam_selector.clear()
        self.cam_selector.addItem("Select Camera...", QVariant())

        if _IC4_INITIALIZED and _ic4_module:
            try:
                tis_devices = _ic4_module.DeviceEnum.devices()
                if tis_devices:
                    log.info(f"Found {len(tis_devices)} TIS camera(s).")
                    for dev_info in tis_devices:
                        display_text = (
                            f"TIS: {dev_info.model_name} (S/N: {dev_info.serial})"
                        )
                        self.cam_selector.addItem(display_text, QVariant(dev_info))
                else:
                    log.info("No TIS cameras found by DeviceEnum.")
                    self.cam_selector.addItem("No TIS cameras found", QVariant())
            except Exception as e:
                log.error(f"Failed to list TIS cameras: {e}")
                self.cam_selector.addItem("Error listing TIS cameras", QVariant())
        else:
            log.warning(
                "TIS SDK not available or not initialized (_IC4_INITIALIZED is %s). TIS cameras cannot be listed here.",
                _IC4_INITIALIZED,
            )
            self.cam_selector.addItem("TIS SDK N/A", QVariant())

        self.cam_selector.setEnabled(self.cam_selector.count() > 1)
        self.cam_selector.blockSignals(False)

        if self.cam_selector.currentIndex() >= 0:
            self._on_camera_selection_changed(self.cam_selector.currentIndex())

    def _on_camera_selection_changed(self, index):
        data = self.cam_selector.itemData(index)
        device_info = data.value() if isinstance(data, QVariant) else data
        if (
            _ic4_module
            and hasattr(_ic4_module, "DeviceInfo")
            and isinstance(device_info, _ic4_module.DeviceInfo)
        ):
            log.info(f"Camera selected: {device_info.model_name}")
        else:
            device_info = None
            log.info("Camera selection: None or invalid.")
        self.camera_selected.emit(device_info)
        if device_info is None:
            self.disable_all_controls()

    def _on_resolution_selection_changed(self, index):
        data = self.res_selector.itemData(index)
        res = data.value() if isinstance(data, QVariant) else data
        if isinstance(res, str):
            self.resolution_selected.emit(res)
        else:
            log.warning(f"Invalid resolution data: {res}")

    @pyqtSlot(list)
    def update_camera_resolutions_list(self, res_list):
        current = self.res_selector.currentData()
        current_str = current.value() if isinstance(current, QVariant) else current
        self.res_selector.blockSignals(True)
        self.res_selector.clear()
        if res_list:
            for r in res_list:
                self.res_selector.addItem(r, QVariant(r))
            idx = (
                self.res_selector.findData(QVariant(current_str)) if current_str else 0
            )
            self.res_selector.setCurrentIndex(idx if idx >= 0 else 0)
            self.res_selector.setEnabled(True)
            self._on_resolution_selection_changed(self.res_selector.currentIndex())
        else:
            self.res_selector.addItem("N/A", QVariant())
            self.res_selector.setEnabled(False)
        self.res_selector.blockSignals(False)

    # Exposure handlers
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

    def _on_auto_exposure_toggled(self, checked):
        self.auto_exposure_toggled.emit(checked)

    # Gain handlers
    def _on_gain_slider_changed(self, s):
        minv, maxv = self.gain_spinbox.minimum(), self.gain_spinbox.maximum()
        proportion = (
            (s - self.gain_slider.minimum())
            / (self.gain_slider.maximum() - self.gain_slider.minimum())
            if self.gain_slider.maximum() != self.gain_slider.minimum()
            else 0
        )
        val = minv + proportion * (maxv - minv)
        self.gain_spinbox.blockSignals(True)
        self.gain_spinbox.setValue(round(val, 1))
        self.gain_spinbox.blockSignals(False)
        self.gain_changed.emit(self.gain_spinbox.value())

    def _on_gain_spinbox_changed(self, val):
        minv, maxv = self.gain_spinbox.minimum(), self.gain_spinbox.maximum()
        proportion = (val - minv) / (maxv - minv) if maxv != minv else 0
        sv = int(
            self.gain_slider.minimum()
            + proportion * (self.gain_slider.maximum() - self.gain_slider.minimum())
        )
        self.gain_slider.blockSignals(True)
        self.gain_slider.setValue(sv)
        self.gain_slider.blockSignals(False)
        self.gain_changed.emit(val)

    def disable_all_controls(self):
        log.debug("CameraControlPanel: Disabling all controls.")
        self.tabs.widget(1).setEnabled(False)
        for w in [
            self.exposure_slider,
            self.exposure_spinbox,
            self.auto_exposure_cb,
            self.gain_slider,
            self.gain_spinbox,
        ]:
            w.setEnabled(False)
            if hasattr(w, "setValue"):
                w.setValue(w.minimum())
        self.res_selector.blockSignals(True)
        self.res_selector.clear()
        self.res_selector.addItem("N/A", QVariant())
        self.res_selector.setEnabled(False)
        self.res_selector.blockSignals(False)
