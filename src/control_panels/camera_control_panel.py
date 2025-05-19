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
    QDoubleSpinBox,  # For Gain if it's float
)
from PyQt5.QtCore import Qt, pyqtSignal, QVariant  # For QComboBox data

# from PyQt5.QtMultimedia import QCameraInfo # No longer primary for TIS

# Conditional import of imagingcontrol4
try:
    import imagingcontrol4 as ic4
    from prim_app import IC4_AVAILABLE, IC4_INITIALIZED  # Check if SDK is usable
except ImportError:
    ic4 = None  # Ensure ic4 is defined
    IC4_AVAILABLE = False
    IC4_INITIALIZED = False


from config import DEFAULT_FRAME_SIZE  # May not be used if TIS cam is active

log = logging.getLogger(__name__)


class CameraControlPanel(QGroupBox):
    # Emits ic4.DeviceInfo object or None if "No Camera" or error
    camera_selected = pyqtSignal(object)  # Use object to allow ic4.DeviceInfo or None
    # Emits resolution string like "WidthxHeight (PixelFormat)"
    resolution_selected = pyqtSignal(str)

    # Property change signals
    exposure_changed = pyqtSignal(int)  # Value in microseconds
    gain_changed = pyqtSignal(float)  # Value in dB (often float for TIS)
    # brightness_changed = pyqtSignal(int)  # Brightness not a direct TIS param
    auto_exposure_toggled = pyqtSignal(bool)

    roi_changed = pyqtSignal(int, int, int, int)  # x, y, w, h
    roi_reset_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Camera Controls", parent)  # Changed title
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self.tabs = QTabWidget()  # Made tabs an instance variable
        layout.addWidget(self.tabs)

        # Basic Controls Tab
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
        self.res_selector.setEnabled(
            False
        )  # Enabled when camera is active and resolutions are known
        basic_layout.addRow("Resolution:", self.res_selector)
        self.tabs.addTab(basic_tab, "Source")  # Renamed tab

        # Adjustments Tab
        adj_tab = QWidget()
        adj_layout = QFormLayout(adj_tab)

        # Exposure
        self.exposure_slider = QSlider(Qt.Horizontal)
        self.exposure_spinbox = QSpinBox()  # For precise value input/display
        self.exposure_spinbox.setKeyboardTracking(False)
        exp_box = QHBoxLayout()
        exp_box.addWidget(self.exposure_slider)
        exp_box.addWidget(self.exposure_spinbox)
        adj_layout.addRow("Exposure (µs):", exp_box)
        self.auto_exposure_cb = QCheckBox("Auto Exposure")
        adj_layout.addRow(self.auto_exposure_cb)

        # Gain
        self.gain_slider = QSlider(
            Qt.Horizontal
        )  # Will map float to int range for slider
        self.gain_spinbox = QDoubleSpinBox()  # For precise float value
        self.gain_spinbox.setDecimals(1)
        self.gain_spinbox.setKeyboardTracking(False)
        gain_box = QHBoxLayout()
        gain_box.addWidget(self.gain_slider)
        gain_box.addWidget(self.gain_spinbox)
        adj_layout.addRow("Gain (dB):", gain_box)

        self.tabs.addTab(adj_tab, "Adjustments")
        adj_tab.setEnabled(
            False
        )  # Enabled when camera is active and properties are known

        # ROI Tab
        roi_tab = QWidget()
        roi_layout = QFormLayout(roi_tab)
        self.roi_x_spinbox = QSpinBox()
        self.roi_y_spinbox = QSpinBox()
        self.roi_w_spinbox = QSpinBox()
        self.roi_h_spinbox = QSpinBox()

        max_dim = (
            max(DEFAULT_FRAME_SIZE) * 4
        )  # Generous upper limit for spinboxes initially
        for spin in (
            self.roi_x_spinbox,
            self.roi_y_spinbox,
            self.roi_w_spinbox,
            self.roi_h_spinbox,
        ):
            spin.setRange(0, max_dim)  # Initial range, will be updated by camera props
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(self._emit_roi_if_changed)  # Connect once

        roi_layout.addRow("Offset X:", self.roi_x_spinbox)
        roi_layout.addRow("Offset Y:", self.roi_y_spinbox)
        roi_layout.addRow("Width:", self.roi_w_spinbox)
        roi_layout.addRow("Height:", self.roi_h_spinbox)

        self.reset_roi_btn = QPushButton("Reset ROI to Full Frame")
        self.reset_roi_btn.clicked.connect(self.roi_reset_requested)  # Forward signal
        roi_layout.addRow(self.reset_roi_btn)
        self.tabs.addTab(roi_tab, "Region of Interest (ROI)")
        roi_tab.setEnabled(
            False
        )  # Enabled when camera is active and ROI props are known

        # Connect adjustment signals
        self.exposure_slider.valueChanged.connect(self._on_exposure_slider_changed)
        self.exposure_spinbox.valueChanged.connect(self._on_exposure_spinbox_changed)
        self.auto_exposure_cb.toggled.connect(self._on_auto_exposure_toggled)

        self.gain_slider.valueChanged.connect(self._on_gain_slider_changed)
        self.gain_spinbox.valueChanged.connect(self._on_gain_spinbox_changed)

        # Populate cameras once, at startup. Could be refreshed via a button.
        self.populate_camera_list()
        self.disable_all_controls()  # Start with controls disabled

    def populate_camera_list(self):
        self.cam_selector.blockSignals(True)
        self.cam_selector.clear()
        self.cam_selector.addItem(
            "Select Camera...", QVariant()
        )  # Placeholder for None

        if IC4_INITIALIZED and ic4:  # Check if SDK was actually initialized
            try:
                tis_devices = ic4.DeviceEnum.devices()
                if tis_devices:
                    for i, dev_info in enumerate(tis_devices):
                        display_text = f"TIS: {dev_info.model_name} ({dev_info.serial})"
                        self.cam_selector.addItem(
                            display_text, QVariant(dev_info)
                        )  # Store DeviceInfo
                        # Optionally select the first TIS camera by default
                        # if i == 0 : self.cam_selector.setCurrentIndex(self.cam_selector.count() -1)
                else:
                    self.cam_selector.addItem("No TIS cameras found", QVariant())
            except Exception as e:
                log.error(f"Failed to list TIS cameras: {e}")
                self.cam_selector.addItem("Error listing TIS cameras", QVariant())
        else:
            log.warning(
                "TIS SDK (imagingcontrol4) not available or not initialized. TIS cameras cannot be listed."
            )
            self.cam_selector.addItem("TIS SDK N/A", QVariant())

        # Add a "Disconnect" option or rely on "Select Camera..."
        self.cam_selector.setEnabled(
            self.cam_selector.count() > 1
            or (
                self.cam_selector.count() == 1
                and self.cam_selector.itemData(0).value() is not None
            )
        )
        self.cam_selector.blockSignals(False)
        # self._on_camera_selection_changed(self.cam_selector.currentIndex()) # Trigger manually if needed

    def _on_camera_selection_changed(self, index):
        selected_data_variant = self.cam_selector.itemData(index)
        if selected_data_variant is not None:
            device_info = (
                selected_data_variant.value()
            )  # This should be ic4.DeviceInfo or None
            self.camera_selected.emit(device_info)  # Emit DeviceInfo or None
            if device_info is None:
                self.disable_all_controls()
        else:  # Should not happen if QVariant() is used for None
            self.camera_selected.emit(None)
            self.disable_all_controls()

    def _on_resolution_selection_changed(self, index):
        res_str = self.res_selector.itemData(
            index
        )  # This should be the resolution string
        if res_str:
            self.resolution_selected.emit(res_str)

    @pyqtSlot(list)  # List of strings like "WidthxHeight (PixelFormat)"
    def update_camera_resolutions_list(self, resolution_strings: list):
        current_res_str = self.res_selector.currentData()
        self.res_selector.blockSignals(True)
        self.res_selector.clear()

        if resolution_strings:
            for res_str in resolution_strings:
                self.res_selector.addItem(
                    res_str, QVariant(res_str)
                )  # Store string as data

            # Try to reselect previous or default
            idx = self.res_selector.findData(QVariant(current_res_str))
            if idx != -1:
                self.res_selector.setCurrentIndex(idx)
            elif self.res_selector.count() > 0:
                self.res_selector.setCurrentIndex(0)  # Select first available

            self.res_selector.setEnabled(True)
            self._on_resolution_selection_changed(
                self.res_selector.currentIndex()
            )  # Emit current selection
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
        # UI update for enabled state of manual exposure will be handled by `update_camera_properties`

    def _on_gain_slider_changed(self, slider_value):
        # Map slider int value back to float for spinbox and signal
        # Assuming slider represents gain * 10 or some other factor if gain has decimals
        # For simplicity, if gain_spinbox min/max are set, slider can map to that.
        # Let's assume gain_spinbox reflects the true float value range.
        min_val = self.gain_spinbox.minimum()
        max_val = self.gain_spinbox.maximum()
        # For direct mapping where slider values are small
        if max_val - min_val < 1000:  # Heuristic for direct mapping or small range
            float_value = min_val + (slider_value / self.gain_slider.maximum()) * (
                max_val - min_val
            )
        else:  # If gain has a large integer range, treat slider as direct int map
            float_value = float(slider_value)

        self.gain_spinbox.blockSignals(True)
        self.gain_spinbox.setValue(round(float_value, 1))  # Round to 1 decimal for dB
        self.gain_spinbox.blockSignals(False)
        self.gain_changed.emit(self.gain_spinbox.value())

    def _on_gain_spinbox_changed(self, value_float):
        self.gain_slider.blockSignals(True)
        # Map float to slider's integer range
        min_val = self.gain_spinbox.minimum()
        max_val = self.gain_spinbox.maximum()
        if max_val - min_val > 0:  # Avoid division by zero
            # If gain has a large integer range, treat slider as direct int map
            if max_val - min_val < 1000:  # Heuristic for float mapping
                slider_val = int(
                    ((value_float - min_val) / (max_val - min_val))
                    * self.gain_slider.maximum()
                )
            else:
                slider_val = int(value_float)
            self.gain_slider.setValue(slider_val)
        self.gain_slider.blockSignals(False)
        self.gain_changed.emit(value_float)

    @pyqtSlot(dict)
    def update_camera_properties_ui(self, props: dict):
        log.debug(f"CameraControlPanel updating UI from properties: {props}")
        controls_data = props.get("controls", {})
        roi_data = props.get("roi", {})

        # --- Update Adjustments Tab ---
        adj_tab_enabled = False

        # Exposure
        exp_props = controls_data.get("exposure", {"enabled": False})
        self.exposure_slider.blockSignals(True)
        self.exposure_spinbox.blockSignals(True)
        self.auto_exposure_cb.blockSignals(True)

        self.exposure_slider.setEnabled(
            exp_props.get("enabled", False) and not exp_props.get("is_auto_on", False)
        )
        self.exposure_spinbox.setEnabled(
            exp_props.get("enabled", False) and not exp_props.get("is_auto_on", False)
        )
        self.auto_exposure_cb.setEnabled(
            exp_props.get("auto_available", False) and exp_props.get("enabled", False)
        )

        if exp_props.get("enabled", False):
            adj_tab_enabled = True
            self.exposure_slider.setRange(
                int(exp_props.get("min", 0)), int(exp_props.get("max", 100000))
            )
            self.exposure_slider.setValue(int(exp_props.get("value", 0)))
            self.exposure_spinbox.setRange(
                int(exp_props.get("min", 0)), int(exp_props.get("max", 100000))
            )
            self.exposure_spinbox.setValue(int(exp_props.get("value", 0)))
            if exp_props.get("auto_available", False):
                self.auto_exposure_cb.setChecked(exp_props.get("is_auto_on", False))

        self.exposure_slider.blockSignals(False)
        self.exposure_spinbox.blockSignals(False)
        self.auto_exposure_cb.blockSignals(False)

        # Gain
        gain_props = controls_data.get("gain", {"enabled": False})
        self.gain_slider.blockSignals(True)
        self.gain_spinbox.blockSignals(True)

        self.gain_slider.setEnabled(gain_props.get("enabled", False))
        self.gain_spinbox.setEnabled(gain_props.get("enabled", False))

        if gain_props.get("enabled", False):
            adj_tab_enabled = True
            min_gain, max_gain = float(gain_props.get("min", 0.0)), float(
                gain_props.get("max", 30.0)
            )
            current_gain = float(gain_props.get("value", 0.0))

            self.gain_spinbox.setRange(min_gain, max_gain)
            self.gain_spinbox.setValue(current_gain)

            # For slider, map float range to int range (e.g., 0-100 or 0-max_gain_int)
            # If gain range is small (e.g. 0-48dB), can multiply by 10 for slider precision
            if max_gain - min_gain < 100:  # Heuristic for precision scaling
                self.gain_slider.setRange(int(min_gain * 10), int(max_gain * 10))
                self.gain_slider.setValue(int(current_gain * 10))
            else:  # Direct integer mapping
                self.gain_slider.setRange(int(min_gain), int(max_gain))
                self.gain_slider.setValue(int(current_gain))

        self.gain_slider.blockSignals(False)
        self.gain_spinbox.blockSignals(False)

        self.tabs.widget(1).setEnabled(adj_tab_enabled)  # Enable "Adjustments" tab

        # --- Update ROI Tab ---
        roi_tab_enabled = False
        self.roi_x_spinbox.blockSignals(True)
        self.roi_y_spinbox.blockSignals(True)
        self.roi_w_spinbox.blockSignals(True)
        self.roi_h_spinbox.blockSignals(True)

        if roi_data and roi_data.get("max_w", 0) > 0:  # Check if ROI data is valid
            roi_tab_enabled = True
            # Max values for W and H are the sensor dimensions
            # Max values for X and Y offsets depend on (SensorDim - CurrentDim)
            self.roi_w_spinbox.setRange(0, roi_data.get("max_w", DEFAULT_FRAME_SIZE[0]))
            self.roi_h_spinbox.setRange(0, roi_data.get("max_h", DEFAULT_FRAME_SIZE[1]))

            # Current ROI width and height
            current_w = roi_data.get("w", DEFAULT_FRAME_SIZE[0])
            current_h = roi_data.get("h", DEFAULT_FRAME_SIZE[1])
            self.roi_w_spinbox.setValue(current_w)
            self.roi_h_spinbox.setValue(current_h)

            # Max offset X = Sensor Width - Current ROI Width
            # Max offset Y = Sensor Height - Current ROI Height
            self.roi_x_spinbox.setRange(
                0, roi_data.get("max_x", roi_data.get("max_w", 0) - current_w)
            )
            self.roi_y_spinbox.setRange(
                0, roi_data.get("max_y", roi_data.get("max_h", 0) - current_h)
            )
            self.roi_x_spinbox.setValue(roi_data.get("x", 0))
            self.roi_y_spinbox.setValue(roi_data.get("y", 0))

        self.roi_x_spinbox.setEnabled(roi_tab_enabled)
        self.roi_y_spinbox.setEnabled(roi_tab_enabled)
        self.roi_w_spinbox.setEnabled(
            roi_tab_enabled
        )  # Width/Height changes may need camera restart
        self.roi_h_spinbox.setEnabled(
            roi_tab_enabled
        )  # For TIS, width/height changes are done by setting new resolution
        self.reset_roi_btn.setEnabled(roi_tab_enabled)

        self.roi_x_spinbox.blockSignals(False)
        self.roi_y_spinbox.blockSignals(False)
        self.roi_w_spinbox.blockSignals(False)
        self.roi_h_spinbox.blockSignals(False)

        self.tabs.widget(2).setEnabled(roi_tab_enabled)  # Enable "ROI" tab

    def _emit_roi_if_changed(self):
        # This is called by each ROI spinbox.
        # It's important that when one spinbox changes, we emit all four values.
        # The check for actual change from previous emission can be done by MainWindow or QtCameraWidget if needed.
        if not self.roi_x_spinbox.signalsBlocked():  # Check if updates are allowed
            self.roi_changed.emit(
                self.roi_x_spinbox.value(),
                self.roi_y_spinbox.value(),
                self.roi_w_spinbox.value(),
                self.roi_h_spinbox.value(),
            )

    def disable_all_controls(self):
        log.debug("CameraControlPanel: Disabling all controls.")
        # Disable Adjustments Tab and its contents
        self.tabs.widget(1).setEnabled(False)
        for widget in [
            self.exposure_slider,
            self.exposure_spinbox,
            self.auto_exposure_cb,
            self.gain_slider,
            self.gain_spinbox,
        ]:
            widget.setEnabled(False)
            if isinstance(widget, QSlider):
                widget.setValue(widget.minimum())
            if isinstance(widget, QSpinBox):
                widget.setValue(widget.minimum())
            if isinstance(widget, QDoubleSpinBox):
                widget.setValue(widget.minimum())
            if isinstance(widget, QCheckBox):
                widget.setChecked(False)
