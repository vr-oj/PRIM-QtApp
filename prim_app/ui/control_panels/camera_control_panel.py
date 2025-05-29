# PRIM-QTAPP/prim_app/ui/control_panels/camera_control_panel.py
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QComboBox,
    QDoubleSpinBox,
    QCheckBox,
    QHBoxLayout,
    QPushButton,
    QTabWidget,
    QFormLayout,
    QSpinBox,
)
from PyQt5.QtCore import pyqtSignal, Qt, pyqtSlot
import logging

log = logging.getLogger(__name__)


class CameraControlPanel(QWidget):
    resolution_changed = pyqtSignal(str)  # Emits "WidthxHeight" string
    pixel_format_changed = pyqtSignal(str)
    auto_exposure_toggled = pyqtSignal(bool)
    exposure_changed = pyqtSignal(float)  # Emits exposure time in µs
    gain_changed = pyqtSignal(float)  # Emits gain in dB
    fps_changed = pyqtSignal(float)  # Emits target FPS

    # Signals for Start/Stop Live buttons, to be connected by MainWindow
    start_stream_requested = pyqtSignal()
    stop_stream_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(300)  # Adjusted minimum width
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(1, 1, 1, 1)  # Minimal margins
        main_layout.setSpacing(1)  # Minimal spacing

        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        # --- Status Tab ---
        self.status_tab = QWidget()
        status_layout = QFormLayout(self.status_tab)
        status_layout.setContentsMargins(3, 3, 3, 3)
        status_layout.setSpacing(3)

        self.cam_model_label = QLabel("N/A")
        self.cam_serial_label = QLabel("N/A")
        self.cam_current_res_label = QLabel("N/A")  # Displays WidthxHeight
        self.cam_current_pix_format_label = QLabel("N/A")
        self.cam_current_fps_label = QLabel("N/A")

        status_layout.addRow("Model:", self.cam_model_label)
        status_layout.addRow("Serial:", self.cam_serial_label)
        status_layout.addRow("Current Resolution:", self.cam_current_res_label)
        status_layout.addRow("Current Pixel Format:", self.cam_current_pix_format_label)
        status_layout.addRow("Current FPS:", self.cam_current_fps_label)
        self.tab_widget.addTab(self.status_tab, "Status")

        # --- Adjustments Tab ---
        self.adjustments_tab = QWidget()
        adj_main_layout = QVBoxLayout(self.adjustments_tab)
        adj_main_layout.setContentsMargins(3, 3, 3, 3)
        adj_main_layout.setSpacing(3)

        controls_layout = QFormLayout()  # Using QFormLayout for compactness

        # Resolution (Combined Width x Height)
        self.res_combo = QComboBox()
        self.res_combo.setToolTip(
            "Target camera resolution (WxH). May require stream restart."
        )
        # Connect to self.resolution_changed (which emits str)
        self.res_combo.currentTextChanged.connect(self.resolution_changed)
        controls_layout.addRow("Resolution:", self.res_combo)

        # Pixel Format
        self.pix_combo = QComboBox()
        self.pix_combo.setToolTip(
            "Target camera pixel format. May require stream restart."
        )
        self.pix_combo.currentTextChanged.connect(self.pixel_format_changed)
        controls_layout.addRow("Pixel Format:", self.pix_combo)

        # Auto Exposure
        self.auto_exp_cb = QCheckBox("Auto Exposure")
        self.auto_exp_cb.toggled.connect(self.auto_exposure_toggled)  # Emits bool
        controls_layout.addRow(self.auto_exp_cb)

        # Manual Exposure Time
        self.exp_spin = QDoubleSpinBox()
        self.exp_spin.setToolTip("Manual exposure time in microseconds (µs)")
        self.exp_spin.setSuffix(" µs")
        self.exp_spin.setDecimals(1)
        self.exp_spin.setRange(1.0, 1000000.0)  # Default, will be updated from camera
        self.exp_spin.setSingleStep(100.0)
        self.exp_spin.valueChanged.connect(self.exposure_changed)  # Emits float
        controls_layout.addRow("Exposure Time:", self.exp_spin)

        # Gain
        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setToolTip("Camera gain (dB)")
        self.gain_spin.setSuffix(" dB")
        self.gain_spin.setDecimals(1)
        self.gain_spin.setRange(0.0, 48.0)  # Default, will be updated from camera
        self.gain_spin.setSingleStep(1.0)
        self.gain_spin.valueChanged.connect(self.gain_changed)  # Emits float
        controls_layout.addRow("Gain:", self.gain_spin)

        # Frame Rate (FPS)
        self.fps_spin = QDoubleSpinBox()
        self.fps_spin.setToolTip("Target camera frame rate (FPS)")
        self.fps_spin.setDecimals(1)
        self.fps_spin.setRange(0.1, 200.0)  # Default, will be updated from camera
        self.fps_spin.setSingleStep(1.0)
        self.fps_spin.valueChanged.connect(self.fps_changed)  # Emits float
        controls_layout.addRow("Frame Rate (FPS):", self.fps_spin)

        adj_main_layout.addLayout(controls_layout)
        adj_main_layout.addStretch(1)  # Push controls up
        self.tab_widget.addTab(self.adjustments_tab, "Adjustments")

        # Start/Stop Live buttons
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Live")
        self.stop_btn = QPushButton("Stop Live")
        # Connect these signals in MainWindow to appropriate slots for starting/stopping SDKCameraThread
        self.start_btn.clicked.connect(self.start_stream_requested)
        self.stop_btn.clicked.connect(self.stop_stream_requested)
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        main_layout.addLayout(btn_layout)

        self.disable_controls_initially()  # Ensure controls are disabled at creation

    def disable_controls_initially(self):
        """Helper to disable all adjustment controls, called at init and when camera disconnects."""
        self.res_combo.setEnabled(False)
        self.pix_combo.setEnabled(False)
        self.auto_exp_cb.setEnabled(False)
        self.exp_spin.setEnabled(False)
        self.gain_spin.setEnabled(False)
        self.fps_spin.setEnabled(False)

        # Start/Stop buttons are also typically managed by MainWindow based on camera thread state,
        # but disabling them here ensures a consistent initial state.
        # MainWindow will enable them as appropriate when the camera thread is ready/running.
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)

        # Also disable the "Adjustments" tab itself. MainWindow can enable it.
        if hasattr(self, "tab_widget") and self.tab_widget.count() > 1:
            self.tab_widget.setTabEnabled(1, False)  # Index 1 for "Adjustments"

    # --- SLOTS TO UPDATE UI FROM MAINWINDOW (which gets data from SDKCameraThread) ---
    @pyqtSlot(dict)
    def update_status_info(self, info: dict):
        self.cam_model_label.setText(info.get("model", "N/A"))
        self.cam_serial_label.setText(info.get("serial", "N/A"))
        res_str = f"{info.get('width', 'N/A')}x{info.get('height', 'N/A')}"
        self.cam_current_res_label.setText(res_str)
        self.cam_current_pix_format_label.setText(info.get("pixel_format", "N/A"))
        self.cam_current_fps_label.setText(f"{info.get('fps', 0.0):.1f}")

    @pyqtSlot(dict)
    def set_exposure_params(self, params: dict):
        log.debug(f"CCP: Updating exposure UI with: {params}")

        # Block signals to prevent feedback loops while programmatically setting values
        self.auto_exp_cb.blockSignals(True)
        self.exp_spin.blockSignals(True)

        self.auto_exp_cb.setChecked(params.get("auto_current", "Off") != "Off")
        self.auto_exp_cb.setEnabled(params.get("auto_is_writable", False))

        min_exp = params.get("time_min_us", 1.0)
        max_exp = params.get("time_max_us", 1000000.0)
        self.exp_spin.setRange(min_exp, max_exp)

        current_exp_val = params.get("time_current_us", 0.0)
        # Ensure value is within the new range before setting it
        current_exp_val = max(min_exp, min(current_exp_val, max_exp))
        self.exp_spin.setValue(current_exp_val)

        # Enable manual exposure spinbox only if auto-exposure is OFF AND the time property is writable
        manual_exp_enabled = (
            params.get("auto_current", "Off") == "Off"
        ) and params.get("time_is_writable", False)
        self.exp_spin.setEnabled(manual_exp_enabled)

        self.auto_exp_cb.blockSignals(False)
        self.exp_spin.blockSignals(False)

    @pyqtSlot(dict)
    def set_gain_params(self, params: dict):
        log.debug(f"CCP: Updating gain UI with: {params}")
        self.gain_spin.blockSignals(True)
        min_gain = params.get("min_db", 0.0)
        max_gain = params.get("max_db", 48.0)
        self.gain_spin.setRange(min_gain, max_gain)

        current_gain_val = params.get("current_db", 0.0)
        current_gain_val = max(min_gain, min(current_gain_val, max_gain))
        self.gain_spin.setValue(current_gain_val)

        self.gain_spin.setEnabled(params.get("is_writable", False))
        self.gain_spin.blockSignals(False)

    @pyqtSlot(dict)
    def set_fps_params(self, params: dict):
        log.debug(f"CCP: Updating FPS UI with: {params}")
        self.fps_spin.blockSignals(True)
        min_fps = params.get("min_fps", 0.1)
        max_fps = params.get("max_fps", 200.0)
        self.fps_spin.setRange(min_fps, max_fps)

        current_fps_val = params.get("current_fps", 0.0)
        current_fps_val = max(min_fps, min(current_fps_val, max_fps))
        self.fps_spin.setValue(current_fps_val)

        self.fps_spin.setEnabled(params.get("is_writable", False))
        self.fps_spin.blockSignals(False)

    @pyqtSlot(list, str)
    def populate_pixel_formats(self, formats: list, current_format_str: str):
        log.debug(
            f"CCP: Populating pixel formats: {formats}, current: {current_format_str}"
        )
        self.pix_combo.blockSignals(True)
        self.pix_combo.clear()

        # Determine if the PixelFormat property is writable from the sender (SDKCameraThread via MainWindow)
        # This is a bit indirect; ideally, writability comes with the params. Assume True for now if options exist.
        # A more robust way: MainWindow gets writability from SDKCameraThread and passes it.
        # For now, enable if list is not empty. Actual set attempt in SDK thread will fail if not writable.
        pixel_format_writable = (
            True  # Placeholder, should be determined from camera properties
        )

        if formats:
            self.pix_combo.addItems(formats)
            idx = self.pix_combo.findText(current_format_str, Qt.MatchFixedString)
            if idx >= 0:
                self.pix_combo.setCurrentIndex(idx)
            self.pix_combo.setEnabled(pixel_format_writable and bool(formats))
        else:
            self.pix_combo.addItem("N/A")
            self.pix_combo.setEnabled(False)
        self.pix_combo.blockSignals(False)

    @pyqtSlot(list, str)
    def populate_resolutions(self, resolutions: list, current_res_str: str):
        # resolutions: list of "WxH" strings. current_res_str is also "WxH" from camera.
        log.debug(
            f"CCP: Populating resolutions: {resolutions}, current: {current_res_str}"
        )
        self.res_combo.blockSignals(True)
        self.res_combo.clear()

        # Enablement of res_combo (i.e., if Width or Height is writable)
        # will be handled by MainWindow's _update_camera_resolution_params slot,
        # which calls self.res_combo.setEnabled()

        if resolutions:
            self.res_combo.addItems(resolutions)
            idx = -1
            if (
                current_res_str
            ):  # current_res_str could be "" if camera reports 0x0 initially
                idx = self.res_combo.findText(current_res_str, Qt.MatchFixedString)

            if idx >= 0:
                self.res_combo.setCurrentIndex(idx)
            elif resolutions:  # If current not found but list exists, select first one
                self.res_combo.setCurrentIndex(0)
            # self.res_combo.setEnabled(True) # Actual enable/disable is handled in MainWindow based on W/H writability
        else:
            self.res_combo.addItem("N/A")
            self.res_combo.setEnabled(False)  # If no resolutions, disable.
        self.res_combo.blockSignals(False)

    # Call this from MainWindow when camera is connected and parameters are known, or disconnected
    def enable_adjustment_controls(self, enable: bool):
        log.debug(
            f"CCP: Setting Adjustments Tab and its basic controls enabled state to: {enable}"
        )

        if hasattr(self, "tab_widget") and self.tab_widget.count() > 1:
            self.tab_widget.setTabEnabled(1, enable)  # Index 1 for "Adjustments"

        # If enabling the tab, the individual controls' enabled state will be
        # determined by their specific parameter update methods (set_exposure_params, etc.)
        # which check for writability.
        # If disabling the tab, force all controls to disabled.
        if not enable:
            self.res_combo.setEnabled(False)
            self.pix_combo.setEnabled(False)
            self.auto_exp_cb.setEnabled(False)
            self.exp_spin.setEnabled(False)
            self.gain_spin.setEnabled(False)
            self.fps_spin.setEnabled(False)
        # If enable is True, we don't explicitly enable all controls here.
        # Their respective param update methods (e.g. set_exposure_params) are responsible for
        # setting their individual enabled states based on property writability from the camera.
