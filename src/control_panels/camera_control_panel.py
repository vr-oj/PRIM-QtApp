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
    roi_changed = pyqtSignal(int, int, int, int)
    roi_reset_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Camera Controls", parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

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

        adj_tab = QWidget()
        adj_layout = QFormLayout(adj_tab)

        self.exposure_slider = QSlider(Qt.Horizontal)
        self.exposure_spinbox = QSpinBox()
        self.exposure_spinbox.setKeyboardTracking(False)
        exp_box = QHBoxLayout()
        exp_box.addWidget(self.exposure_slider)
        exp_box.addWidget(self.exposure_spinbox)
        adj_layout.addRow("Exposure (µs):", exp_box)
        self.auto_exposure_cb = QCheckBox("Auto Exposure")
        adj_layout.addRow(self.auto_exposure_cb)

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

        roi_tab = QWidget()
        roi_layout = QFormLayout(roi_tab)
        self.roi_x_spinbox = QSpinBox()
        self.roi_y_spinbox = QSpinBox()
        self.roi_w_spinbox = QSpinBox()
        self.roi_h_spinbox = QSpinBox()

        max_dim = max(DEFAULT_FRAME_SIZE) * 4
        for spin in (
            self.roi_x_spinbox,
            self.roi_y_spinbox,
            self.roi_w_spinbox,
            self.roi_h_spinbox,
        ):
            spin.setRange(0, max_dim)
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(self._emit_roi_if_changed)

        roi_layout.addRow("Offset X:", self.roi_x_spinbox)
        roi_layout.addRow("Offset Y:", self.roi_y_spinbox)
        roi_layout.addRow("Width:", self.roi_w_spinbox)
        roi_layout.addRow("Height:", self.roi_h_spinbox)

        self.reset_roi_btn = QPushButton("Reset ROI to Full Frame")
        self.reset_roi_btn.clicked.connect(self.roi_reset_requested)
        roi_layout.addRow(self.reset_roi_btn)
        self.tabs.addTab(roi_tab, "Region of Interest (ROI)")
        roi_tab.setEnabled(False)

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
                    for i, dev_info in enumerate(tis_devices):
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

        self.cam_selector.setEnabled(
            self.cam_selector.count() > 1
            or (
                self.cam_selector.count() == 1
                and self.cam_selector.itemData(0).value() is not None
            )
        )
        self.cam_selector.blockSignals(False)

        if self.cam_selector.currentIndex() >= 0:
            self._on_camera_selection_changed(self.cam_selector.currentIndex())

    def _on_camera_selection_changed(self, index):
        selected_data_variant = self.cam_selector.itemData(index)
        device_info = None
        actual_data = None

        if selected_data_variant is not None:
            if isinstance(selected_data_variant, QVariant):
                actual_data = selected_data_variant.value()
            else:
                actual_data = selected_data_variant

        if (
            _ic4_module
            and hasattr(_ic4_module, "DeviceInfo")
            and isinstance(actual_data, _ic4_module.DeviceInfo)
        ):
            device_info = actual_data
            log.info(
                f"Camera selected: {device_info.model_name if device_info else 'None'}"
            )
        elif actual_data is None:
            log.info("Camera selection: None (e.g., 'Select Camera...' chosen)")
            device_info = None
        else:
            log.warning(
                f"Unexpected data type from cam_selector: {type(actual_data)}. Treating as no selection."
            )
            device_info = None

        self.camera_selected.emit(device_info)
        if device_info is None:
            self.disable_all_controls()

    def _on_resolution_selection_changed(self, index):
        # --- THIS IS THE CORRECTED PART for AttributeError ---
        current_data = self.res_selector.itemData(index)
        res_str = None
        if isinstance(current_data, QVariant):
            res_str = current_data.value()
        else:
            res_str = current_data
        # --- End of corrected part ---

        if res_str and isinstance(res_str, str):
            self.resolution_selected.emit(res_str)
        elif res_str is not None:
            log.warning(f"Resolution combobox data was not a string: {type(res_str)}")

    @pyqtSlot(list)
    def update_camera_resolutions_list(self, resolution_strings: list):
        # --- THIS METHOD IS CORRECTED ---
        current_selection_data = self.res_selector.currentData()
        current_res_str = None
        # Correctly unwrap QVariant if present
        if isinstance(current_selection_data, QVariant):
            current_res_str = current_selection_data.value()
        else:  # If it's already the direct data (e.g. string, or None for placeholder)
            current_res_str = current_selection_data

        self.res_selector.blockSignals(True)
        self.res_selector.clear()

        if resolution_strings:
            for res_str_item in resolution_strings:
                self.res_selector.addItem(res_str_item, QVariant(res_str_item))

            idx = -1
            if current_res_str and isinstance(current_res_str, str):
                idx = self.res_selector.findData(
                    QVariant(current_res_str)
                )  # Find data by QVariant(string)

            if idx != -1:
                self.res_selector.setCurrentIndex(idx)
            elif self.res_selector.count() > 0:
                self.res_selector.setCurrentIndex(0)

            self.res_selector.setEnabled(True)
            # Emit current selection only if list is not empty and something is selected.
            # Check currentIndex before calling itemData to avoid issues if list is empty after clear
            if self.res_selector.count() > 0 and self.res_selector.currentIndex() >= 0:
                self._on_resolution_selection_changed(self.res_selector.currentIndex())
        else:
            self.res_selector.addItem("N/A", QVariant())
            self.res_selector.setEnabled(False)
        self.res_selector.blockSignals(False)
        # --- End of corrected method ---

    def _on_exposure_slider_changed(self, value):
        self.exposure_spinbox.blockSignals(True)
        self.exposure_spinbox.setValue(value)
        self.exposure_spinbox.blockSignals(False)
        self.exposure_changed.emit(value)

    def _on_exposure_spinbox_changed(self, value):
        self.exposure_slider.blockSignals(True)
        self.exposure_slider.setValue(value)
        self.exposure_slider.blockSignals(False)
        self.exposure_changed.emit(value)

    def _on_auto_exposure_toggled(self, checked):
        self.auto_exposure_toggled.emit(checked)

    def _on_gain_slider_changed(self, slider_value):
        min_val = self.gain_spinbox.minimum()
        max_val = self.gain_spinbox.maximum()

        float_value = min_val
        slider_range = self.gain_slider.maximum() - self.gain_slider.minimum()
        if slider_range > 0:
            proportion = (slider_value - self.gain_slider.minimum()) / slider_range
            float_value = min_val + proportion * (max_val - min_val)
        elif slider_value == self.gain_slider.minimum():
            float_value = min_val
        elif slider_value == self.gain_slider.maximum():
            float_value = max_val

        self.gain_spinbox.blockSignals(True)
        self.gain_spinbox.setValue(round(float_value, 1))
        self.gain_spinbox.blockSignals(False)
        self.gain_changed.emit(self.gain_spinbox.value())

    def _on_gain_spinbox_changed(self, value_float):
        self.gain_slider.blockSignals(True)
        min_val_spin = self.gain_spinbox.minimum()
        max_val_spin = self.gain_spinbox.maximum()
        slider_min_int = self.gain_slider.minimum()
        slider_max_int = self.gain_slider.maximum()

        slider_val = slider_min_int
        spin_range = max_val_spin - min_val_spin
        if spin_range > 0:
            proportion = (value_float - min_val_spin) / spin_range
            slider_val = int(
                slider_min_int + proportion * (slider_max_int - slider_min_int)
            )
            slider_val = max(slider_min_int, min(slider_val, slider_max_int))
        elif value_float <= min_val_spin:
            slider_val = slider_min_int
        elif value_float >= max_val_spin:
            slider_val = slider_max_int

        self.gain_slider.setValue(slider_val)
        self.gain_slider.blockSignals(False)
        self.gain_changed.emit(value_float)

    @pyqtSlot(dict)
    def update_camera_properties_ui(self, props: dict):
        log.debug(f"CameraControlPanel updating UI from properties: {props}")
        controls_data = props.get("controls", {})
        roi_data = props.get("roi", {})

        adj_tab_enabled = False

        exp_props = controls_data.get("exposure", {"enabled": False})
        self.exposure_slider.blockSignals(True)
        self.exposure_spinbox.blockSignals(True)
        self.auto_exposure_cb.blockSignals(True)

        exp_is_controllable = exp_props.get("enabled", False)
        exp_is_auto_on = exp_props.get("is_auto_on", False)
        exp_auto_available = exp_props.get("auto_available", False)

        self.exposure_slider.setEnabled(exp_is_controllable and not exp_is_auto_on)
        self.exposure_spinbox.setEnabled(exp_is_controllable and not exp_is_auto_on)
        self.auto_exposure_cb.setEnabled(exp_is_controllable and exp_auto_available)

        if exp_is_controllable:
            adj_tab_enabled = True
            min_exp, max_exp = int(exp_props.get("min", 0)), int(
                exp_props.get("max", 100000)
            )
            val_exp = int(exp_props.get("value", 0))
            self.exposure_slider.setRange(min_exp, max_exp)
            self.exposure_slider.setValue(val_exp)
            self.exposure_spinbox.setRange(min_exp, max_exp)
            self.exposure_spinbox.setValue(val_exp)
            if exp_auto_available:
                self.auto_exposure_cb.setChecked(exp_is_auto_on)

        self.exposure_slider.blockSignals(False)
        self.exposure_spinbox.blockSignals(False)
        self.auto_exposure_cb.blockSignals(False)

        gain_props = controls_data.get("gain", {"enabled": False})
        self.gain_slider.blockSignals(True)
        self.gain_spinbox.blockSignals(True)

        gain_is_controllable = gain_props.get("enabled", False)
        self.gain_slider.setEnabled(gain_is_controllable)
        self.gain_spinbox.setEnabled(gain_is_controllable)

        if gain_is_controllable:
            adj_tab_enabled = True
            min_gain, max_gain = float(gain_props.get("min", 0.0)), float(
                gain_props.get("max", 30.0)
            )
            current_gain = float(gain_props.get("value", 0.0))

            self.gain_spinbox.setRange(min_gain, max_gain)
            self.gain_spinbox.setValue(current_gain)

            slider_current_min = self.gain_slider.minimum()
            slider_current_max = self.gain_slider.maximum()
            if slider_current_max == slider_current_min:
                self.gain_slider.setRange(0, 1000)
                slider_current_min, slider_current_max = 0, 1000

            slider_val = slider_current_min
            gain_range = max_gain - min_gain
            if gain_range > 0:
                proportion = (current_gain - min_gain) / gain_range
                slider_val = int(
                    slider_current_min
                    + proportion * (slider_current_max - slider_current_min)
                )
            elif current_gain <= min_gain:
                slider_val = slider_current_min
            elif current_gain >= max_gain:
                slider_val = slider_current_max

            self.gain_slider.setValue(slider_val)

        self.gain_slider.blockSignals(False)
        self.gain_spinbox.blockSignals(False)

        self.tabs.widget(1).setEnabled(adj_tab_enabled)

        roi_tab_enabled = False
        self.roi_x_spinbox.blockSignals(True)
        self.roi_y_spinbox.blockSignals(True)
        self.roi_w_spinbox.blockSignals(True)
        self.roi_h_spinbox.blockSignals(True)

        if roi_data and roi_data.get("max_w", 0) > 0:
            roi_tab_enabled = True

            max_w_sensor = roi_data.get("max_w", DEFAULT_FRAME_SIZE[0])
            max_h_sensor = roi_data.get("max_h", DEFAULT_FRAME_SIZE[1])

            current_roi_w = roi_data.get("w", max_w_sensor)
            current_roi_h = roi_data.get("h", max_h_sensor)
            current_roi_x = roi_data.get("x", 0)
            current_roi_y = roi_data.get("y", 0)

            self.roi_w_spinbox.setRange(0, max_w_sensor)
            self.roi_h_spinbox.setRange(0, max_h_sensor)
            self.roi_w_spinbox.setValue(current_roi_w)
            self.roi_h_spinbox.setValue(current_roi_h)

            max_offset_x = max(0, max_w_sensor - current_roi_w)
            max_offset_y = max(0, max_h_sensor - current_roi_h)
            self.roi_x_spinbox.setRange(0, roi_data.get("max_x", max_offset_x))
            self.roi_y_spinbox.setRange(0, roi_data.get("max_y", max_offset_y))
            self.roi_x_spinbox.setValue(current_roi_x)
            self.roi_y_spinbox.setValue(current_roi_y)

        self.roi_x_spinbox.setEnabled(roi_tab_enabled)
        self.roi_y_spinbox.setEnabled(roi_tab_enabled)
        self.roi_w_spinbox.setEnabled(roi_tab_enabled and False)
        self.roi_h_spinbox.setEnabled(roi_tab_enabled and False)
        self.reset_roi_btn.setEnabled(roi_tab_enabled)

        self.roi_x_spinbox.blockSignals(False)
        self.roi_y_spinbox.blockSignals(False)
        self.roi_w_spinbox.blockSignals(False)
        self.roi_h_spinbox.blockSignals(False)

        self.tabs.widget(2).setEnabled(roi_tab_enabled)

    def _emit_roi_if_changed(self):
        if not self.roi_x_spinbox.signalsBlocked():
            self.roi_changed.emit(
                self.roi_x_spinbox.value(),
                self.roi_y_spinbox.value(),
                self.roi_w_spinbox.value(),
                self.roi_h_spinbox.value(),
            )

    def disable_all_controls(self):
        log.debug("CameraControlPanel: Disabling all controls.")
        self.tabs.widget(1).setEnabled(False)
        self.tabs.widget(2).setEnabled(False)

        for widget in [
            self.exposure_slider,
            self.exposure_spinbox,
            self.auto_exposure_cb,
            self.gain_slider,
            self.gain_spinbox,
            self.roi_x_spinbox,
            self.roi_y_spinbox,
            self.roi_w_spinbox,
            self.roi_h_spinbox,
            self.reset_roi_btn,
        ]:
            widget.setEnabled(False)
            if isinstance(widget, QSlider):
                widget.setValue(widget.minimum())
            if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                min_val, max_val = widget.minimum(), widget.maximum()
                if min_val <= max_val:
                    widget.setValue(min_val)
            if isinstance(widget, QCheckBox):
                widget.setChecked(False)

        self.res_selector.blockSignals(True)
        self.res_selector.clear()
        self.res_selector.addItem("N/A", QVariant())
        self.res_selector.setEnabled(False)
        self.res_selector.blockSignals(False)
