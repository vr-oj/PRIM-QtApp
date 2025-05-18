from PyQt5.QtWidgets import (
    QWidget,
    QGroupBox,
    QTabWidget,
    QFormLayout,
    QHBoxLayout,
    QLabel,
)
from PyQt5.QtCore import pyqtSignal


class TopControlPanel(QWidget):
    camera_selected = pyqtSignal(int, str)
    resolution_selected = pyqtSignal(str)
    exposure_changed = pyqtSignal(int)
    gain_changed = pyqtSignal(int)
    brightness_changed = pyqtSignal(int)
    auto_exposure_toggled = pyqtSignal(bool)
    roi_changed = pyqtSignal(int, int, int, int)
    roi_reset_requested = pyqtSignal()

    x_axis_limits_changed = pyqtSignal(float, float)
    y_axis_limits_changed = pyqtSignal(float, float)
    export_plot_image_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 2, 5, 2)
        layout.setSpacing(10)

        self.camera_controls = CameraControlPanel(self)
        layout.addWidget(self.camera_controls, 1)

        status_box = QGroupBox("PRIM Device Status")
        status_layout = QFormLayout(status_box)
        self.conn_lbl = QLabel("Disconnected")
        self.conn_lbl.setStyleSheet("font-weight:bold;color:#D6C832;")
        status_layout.addRow("Connection:", self.conn_lbl)
        self.idx_lbl = QLabel("N/A")
        status_layout.addRow("Device Frame #:", self.idx_lbl)
        self.time_lbl = QLabel("N/A")
        status_layout.addRow("Device Time (s):", self.time_lbl)
        self.pres_lbl = QLabel("N/A")
        self.pres_lbl.setStyleSheet("font-size:12pt;font-weight:bold;")
        status_layout.addRow("Current Pressure:", self.pres_lbl)
        layout.addWidget(status_box, 1)

        self.plot_controls = PlotControlPanel(self)
        layout.addWidget(self.plot_controls, 1)

        # Forward camera signals
        cc = self.camera_controls
        cc.camera_selected.connect(self.camera_selected)
        cc.resolution_selected.connect(self.resolution_selected)
        cc.exposure_changed.connect(self.exposure_changed)
        cc.gain_changed.connect(self.gain_changed)
        cc.brightness_changed.connect(self.brightness_changed)
        cc.auto_exposure_toggled.connect(self.auto_exposure_toggled)
        cc.roi_changed.connect(self.roi_changed)
        cc.roi_reset_requested.connect(self.roi_reset_requested)

        # Forward plot signals
        pc = self.plot_controls
        pc.x_axis_limits_changed.connect(self.x_axis_limits_changed)
        pc.y_axis_limits_changed.connect(self.y_axis_limits_changed)
        pc.export_plot_image_requested.connect(self.export_plot_image_requested)

    def update_camera_ui_from_properties(self, props):
        controls = props.get("controls", {})
        # Enable Adjustments tab if any control enabled
        adjustments_enabled = any(
            controls.get(name, {}).get("enabled", False)
            for name in ("exposure", "gain", "brightness")
        )
        tabs = self.camera_controls.findChild(QTabWidget)
        if tabs:
            tabs.widget(1).setEnabled(adjustments_enabled)

        for name, cfg in controls.items():
            self.camera_controls.update_control_from_properties(name, cfg)

        self.camera_controls.update_roi_controls(props.get("roi", {}))

    def disable_all_camera_controls(self):
        off = {"enabled": False, "value": 0, "min": 0, "max": 0, "is_auto_on": False}
        for name in ("exposure", "gain", "brightness"):
            self.camera_controls.update_control_from_properties(name, off)
        self.camera_controls.update_roi_controls({"max_w": 0, "max_h": 0})
        res = self.camera_controls.res_selector
        res.clear()
        res.setEnabled(False)
        tabs = self.camera_controls.findChild(QTabWidget)
        if tabs:
            tabs.widget(0).setEnabled(True)
            tabs.widget(1).setEnabled(False)

    def update_connection_status(self, text, connected):
        self.conn_lbl.setText(text)
        color = (
            "#A3BE8C" if connected else ("#BF616A" if "Error" in text else "#D6C832")
        )
        self.conn_lbl.setStyleSheet(f"font-weight:bold;color:{color};")

    def update_prim_data(self, idx, t_dev, p_dev):
        self.idx_lbl.setText(str(idx))
        self.time_lbl.setText(f"{t_dev:.2f}")
        self.pres_lbl.setText(f"{p_dev:.2f} mmHg")

    def update_camera_resolutions(self, modes):
        combo = self.camera_controls.res_selector
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Select…", "")
        for m in modes:
            combo.addItem(m, m)
        combo.setEnabled(bool(modes))
        combo.blockSignals(False)
