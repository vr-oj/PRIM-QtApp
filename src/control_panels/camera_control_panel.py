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

# --- Robust import of prim_app flags and imagingcontrol4 ---
# This section attempts to get the SDK initialization status from prim_app.py
_IC4_AVAILABLE = False
_IC4_INITIALIZED = False
_ic4_module = None  # Will hold the 'imagingcontrol4' module if loaded

try:
    import sys
    import os

    # Dynamically add the 'src' directory (parent of 'control_panels') to sys.path
    # This helps Python find 'prim_app' when 'camera_control_panel.py' is imported.
    current_file_dir = os.path.dirname(os.path.abspath(__file__))  # .../control_panels
    src_dir = os.path.dirname(current_file_dir)  # .../src
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)  # Prepend to give it priority

    import prim_app  # Import the prim_app module directly

    _IC4_AVAILABLE = getattr(prim_app, "IC4_AVAILABLE", False)
    _IC4_INITIALIZED = getattr(prim_app, "IC4_INITIALIZED", False)

    if _IC4_INITIALIZED:
        import imagingcontrol4 as ic4_sdk  # Actual import of the SDK

        _ic4_module = ic4_sdk
    logging.getLogger(__name__).info(
        "Successfully checked prim_app for IC4 flags. Initialized: %s", _IC4_INITIALIZED
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
# --- End of robust import section ---


from config import DEFAULT_FRAME_SIZE

log = logging.getLogger(__name__)  # Use module's logger after initial setup


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

        # Use the locally scoped _IC4_INITIALIZED and _ic4_module
        if _IC4_INITIALIZED and _ic4_module:
            try:
                tis_devices = _ic4_module.DeviceEnum.devices()
                if tis_devices:
                    for i, dev_info in enumerate(tis_devices):
                        display_text = f"TIS: {dev_info.model_name} ({dev_info.serial})"
                        self.cam_selector.addItem(display_text, QVariant(dev_info))
                else:
                    self.cam_selector.addItem("No TIS cameras found", QVariant())
            except Exception as e:
                log.error(f"Failed to list TIS cameras: {e}")
                self.cam_selector.addItem("Error listing TIS cameras", QVariant())
        else:
            # This log is now more informative if the flags were not correctly read
            log.warning(
                "TIS SDK not available or not initialized (_IC4_INITIALIZED is False). TIS cameras cannot be listed here."
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
        if (
            self.cam_selector.currentIndex() >= 0
        ):  # Ensure an item is selected before manually triggering
            self._on_camera_selection_changed(self.cam_selector.currentIndex())

    def _on_camera_selection_changed(self, index):
        selected_data_variant = self.cam_selector.itemData(index)
        device_info = None  # Default to None
        if selected_data_variant is not None:
            val = selected_data_variant.value()
            # Check if val is an instance of DeviceInfo from the _ic4_module we imported
            if (
                _ic4_module
                and hasattr(_ic4_module, "DeviceInfo")
                and isinstance(val, _ic4_module.DeviceInfo)
            ):
                device_info = val

        self.camera_selected.emit(device_info)
        if device_info is None:
            self.disable_all_controls()

    def _on_resolution_selection_changed(self, index):
        res_str_variant = self.res_selector.itemData(index)
        if res_str_variant is not None:
            res_str = res_str_variant.value()
            if res_str:
                self.resolution_selected.emit(res_str)

    @pyqtSlot(list)
    def update_camera_resolutions_list(self, resolution_strings: list):
        current_res_str_variant = self.res_selector.currentData()
        current_res_str = (
            current_res_str_variant.value() if current_res_str_variant else None
        )

        self.res_selector.blockSignals(True)
        self.res_selector.clear()

        if resolution_strings:
            for res_str in resolution_strings:
                self.res_selector.addItem(res_str, QVariant(res_str))

            idx = (
                self.res_selector.findData(QVariant(current_res_str))
                if current_res_str
                else -1
            )
            if idx != -1:
                self.res_selector.setCurrentIndex(idx)
            elif self.res_selector.count() > 0:
                self.res_selector.setCurrentIndex(0)

            self.res_selector.setEnabled(True)
            if self.res_selector.currentIndex() >= 0:
                self._on_resolution_selection_changed(self.res_selector.currentIndex())
        else:
            self.res_selector.addItem("N/A", QVariant())
            self.res_selector.setEnabled(False)
        self.res_selector.blockSignals(False)

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
        if (
            self.gain_slider.maximum() > self.gain_slider.minimum()
        ):  # Ensure slider has a range
            # Proportionally map slider value to spinbox float range
            proportion = (slider_value - self.gain_slider.minimum()) / (
                self.gain_slider.maximum() - self.gain_slider.minimum()
            )
            float_value = min_val + proportion * (max_val - min_val)
        elif slider_value == self.gain_slider.minimum():
            float_value = min_val
        elif (
            slider_value == self.gain_slider.maximum()
        ):  # If min==max, this won't be distinct from above
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
        if max_val_spin - min_val_spin > 0:
            proportion = (value_float - min_val_spin) / (max_val_spin - min_val_spin)
            slider_val = int(
                slider_min_int + proportion * (slider_max_int - slider_min_int)
            )
            slider_val = max(slider_min_int, min(slider_val, slider_max_int))  # Clamp
        elif value_float == min_val_spin:
            slider_val = slider_min_int

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

            # Sensible default for slider if not yet ranged, e.g., 0-1000
            if (
                self.gain_slider.maximum() == self.gain_slider.minimum()
            ):  # If not ranged yet
                self.gain_slider.setRange(0, 1000)  # Default precision range

            slider_min_int = self.gain_slider.minimum()
            slider_max_int = self.gain_slider.maximum()
            slider_val = slider_min_int
            if max_gain - min_gain > 0:
                proportion = (current_gain - min_gain) / (max_gain - min_gain)
                slider_val = int(
                    slider_min_int + proportion * (slider_max_int - slider_min_int)
                )
            elif current_gain == min_gain:
                slider_val = slider_min_int

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
        self.tabs.widget(1).setEnabled(False)  # Adjustments tab
        self.tabs.widget(2).setEnabled(False)  # ROI tab

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
                # Ensure min is not greater than max before setting value to avoid errors
                min_val, max_val = widget.minimum(), widget.maximum()
                if min_val <= max_val:
                    widget.setValue(min_val)
                # else: log.debug(f"Spinbox {widget.objectName()} has invalid range min={min_val} > max={max_val}")
            if isinstance(widget, QCheckBox):
                widget.setChecked(False)

        self.res_selector.blockSignals(True)
        self.res_selector.clear()
        self.res_selector.addItem("N/A", QVariant())
        self.res_selector.setEnabled(False)
        self.res_selector.blockSignals(False)
