# PRIM-QTAPP/prim_app/ui/control_panels/camera_control_panel.py
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QComboBox,
    QDoubleSpinBox,
    QSlider,
    QCheckBox,
    QHBoxLayout,
    QPushButton,
    QTabWidget,  # Added
    QFormLayout,  # Added for the status tab
    QSizePolicy,  # Added for a spacer
)
from PyQt5.QtCore import pyqtSignal, Qt


class CameraControlPanel(QWidget):
    # Signals remain the same
    resolution_changed = pyqtSignal(str)
    pixel_format_changed = pyqtSignal(str)
    auto_exposure_toggled = pyqtSignal(bool)
    exposure_changed = pyqtSignal(float)
    gain_changed = pyqtSignal(float)
    fps_changed = pyqtSignal(float)
    start_stream = pyqtSignal()
    stop_stream = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(250)  # Adjusted minimum width slightly for tabs
        # Main layout for this panel will be vertical, holding the TabWidget and possibly buttons
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(1, 1, 1, 1)  # Reduced margins
        main_layout.setSpacing(1)  # Reduced spacing

        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        # --- Create Status Tab ---
        self.status_tab = QWidget()
        status_layout = QFormLayout(self.status_tab)
        status_layout.setContentsMargins(1, 1, 1, 1)
        status_layout.setSpacing(1)

        self.cam_model_label = QLabel("N/A")
        self.cam_serial_label = QLabel("N/A")
        self.cam_current_res_label = QLabel("N/A")
        self.cam_current_pix_format_label = QLabel("N/A")
        self.cam_current_fps_label = QLabel("N/A")

        status_layout.addRow("Model:", self.cam_model_label)
        status_layout.addRow("Serial:", self.cam_serial_label)
        status_layout.addRow("Resolution:", self.cam_current_res_label)
        status_layout.addRow("Pixel Format:", self.cam_current_pix_format_label)
        status_layout.addRow("FPS:", self.cam_current_fps_label)

        self.tab_widget.addTab(self.status_tab, "Status")

        # --- Create Adjustments Tab ---
        self.adjustments_tab = QWidget()
        adjustments_main_layout = QVBoxLayout(
            self.adjustments_tab
        )  # Use QVBoxLayout to allow sections
        adjustments_main_layout.setContentsMargins(1, 1, 1, 1)
        adjustments_main_layout.setSpacing(1)

        # We can use QFormLayout or QVBoxLayouts within this for better grouping if needed
        controls_layout = QFormLayout()  # Using QFormLayout for compactness of controls

        # Resolution dropdown
        self.res_combo = QComboBox()
        self.res_combo.setToolTip("Target camera resolution (requires stream restart)")
        self.res_combo.currentTextChanged.connect(self.resolution_changed)
        controls_layout.addRow("Resolution:", self.res_combo)

        # Pixel format dropdown
        self.pix_combo = QComboBox()
        self.pix_combo.setToolTip(
            "Target camera pixel format (requires stream restart)"
        )
        self.pix_combo.currentTextChanged.connect(self.pixel_format_changed)
        controls_layout.addRow("Pixel Format:", self.pix_combo)

        # Auto Exposure
        self.auto_exp_cb = QCheckBox("Auto Exposure")
        self.auto_exp_cb.stateChanged.connect(
            lambda state: self.auto_exposure_toggled.emit(state == Qt.Checked)
        )
        controls_layout.addRow(self.auto_exp_cb)

        # Manual Exposure time
        self.exp_spin = QDoubleSpinBox()
        self.exp_spin.setToolTip("Manual exposure time in microseconds (µs)")
        self.exp_spin.setSuffix(" µs")  # More explicit suffix
        self.exp_spin.setDecimals(1)  # Or more if needed
        self.exp_spin.setRange(
            10.0, 1000000.0
        )  # Example range, will be updated from camera
        self.exp_spin.setSingleStep(100.0)
        self.exp_spin.valueChanged.connect(self.exposure_changed)
        controls_layout.addRow("Exposure Time:", self.exp_spin)

        # Gain (using QDoubleSpinBox for more precision than QSlider if gain is float)
        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setToolTip("Camera gain (dB or relative units)")
        self.gain_spin.setSuffix(" dB")  # Example suffix
        self.gain_spin.setDecimals(1)
        self.gain_spin.setRange(0.0, 48.0)  # Example range, will be updated
        self.gain_spin.valueChanged.connect(lambda v: self.gain_changed.emit(float(v)))
        controls_layout.addRow("Gain:", self.gain_spin)

        # Frame rate
        self.fps_spin = QDoubleSpinBox()
        self.fps_spin.setToolTip("Target camera frame rate (FPS)")
        self.fps_spin.setRange(0.1, 200.0)  # Example range, will be updated
        self.fps_spin.setSingleStep(1.0)
        self.fps_spin.setDecimals(1)
        self.fps_spin.valueChanged.connect(self.fps_changed)
        controls_layout.addRow("Frame Rate (FPS):", self.fps_spin)

        adjustments_main_layout.addLayout(controls_layout)
        adjustments_main_layout.addStretch(1)  # Add stretch to push controls up

        self.tab_widget.addTab(self.adjustments_tab, "Adjustments")

        # Start/Stop Live buttons (can remain outside tabs or be moved into a tab)
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Live")
        self.start_btn.clicked.connect(self.start_stream)
        self.stop_btn = QPushButton("Stop Live")
        self.stop_btn.clicked.connect(self.stop_stream)
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)

        main_layout.addLayout(btn_layout)  # Add buttons below the tab widget

        # Initial state of controls (will be managed by MainWindow enabling/disabling CameraControlPanel)
        # For now, individual controls are created but their actual functionality depends on MainWindow logic

    # Methods to update status labels (to be called from MainWindow)
    def update_status_info(
        self, model="N/A", serial="N/A", resolution="N/A", pix_format="N/A", fps="N/A"
    ):
        self.cam_model_label.setText(model)
        self.cam_serial_label.setText(serial)
        self.cam_current_res_label.setText(resolution)
        self.cam_current_pix_format_label.setText(pix_format)
        self.cam_current_fps_label.setText(fps)

    # Methods to update adjustment control ranges/values (to be called from MainWindow)
    @pyqtSlot(dict)
    def set_exposure_params(self, params: dict):
        # Receive full exposure params from the SDK thread and update the UI controls.
        # Unpack
        auto_curr = params.get("auto_current", "Off") or "Off"
        auto_writable = params.get("auto_is_writable", False)
        time_curr = params.get("time_current_us", 0.0) or 0.0
        time_min = params.get("time_min_us", 0.0) or 0.0
        time_max = params.get("time_max_us", time_curr or 1e6)
        time_writable = params.get("time_is_writable", False)

        # Auto-exposure checkbox
        self.auto_exp_cb.blockSignals(True)
        self.auto_exp_cb.setChecked(auto_curr != "Off")
        self.auto_exp_cb.setEnabled(auto_writable)
        self.auto_exp_cb.blockSignals(False)

        # Manual exposure spinbox
        self.exp_spin.blockSignals(True)
        self.exp_spin.setRange(time_min, time_max)
        self.exp_spin.setValue(time_curr)
        # Only allow manual edits when auto is Off
        self.exp_spin.setEnabled(time_writable and auto_curr == "Off")
        self.exp_spin.blockSignals(False)

    def update_gain_controls(
        self, enabled: bool, value: float, min_val: float, max_val: float
    ):
        self.gain_spin.setRange(min_val, max_val)
        self.gain_spin.setValue(value)
        self.gain_spin.setEnabled(enabled)

    def update_fps_controls(
        self, enabled: bool, value: float, min_val: float, max_val: float
    ):
        self.fps_spin.setRange(min_val, max_val)
        self.fps_spin.setValue(value)
        self.fps_spin.setEnabled(enabled)

    def populate_resolutions(self, resolutions: list, current_res_str: str = None):
        self.res_combo.blockSignals(True)
        self.res_combo.clear()
        self.res_combo.addItems(resolutions)
        if current_res_str:
            idx = self.res_combo.findText(current_res_str)
            if idx >= 0:
                self.res_combo.setCurrentIndex(idx)
        self.res_combo.blockSignals(False)

    def populate_pixel_formats(self, formats: list, current_format_str: str = None):
        self.pix_combo.blockSignals(True)
        self.pix_combo.clear()
        self.pix_combo.addItems(formats)
        if current_format_str:
            idx = self.pix_combo.findText(current_format_str)
            if idx >= 0:
                self.pix_combo.setCurrentIndex(idx)
        self.pix_combo.blockSignals(False)
