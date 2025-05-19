import logging

from PyQt5.QtWidgets import (
    QWidget,
    QGroupBox,
    QTabWidget,
    QFormLayout,
    QHBoxLayout,
    QLabel,
)
from PyQt5.QtCore import pyqtSignal, QObject, pyqtSlot  # Added pyqtSlot here

from .camera_control_panel import CameraControlPanel
from .plot_control_panel import PlotControlPanel

try:
    import imagingcontrol4 as ic4
except ImportError:
    ic4 = None

log = logging.getLogger(__name__)


class TopControlPanel(QWidget):
    camera_selected = pyqtSignal(object)
    resolution_selected = pyqtSignal(str)
    exposure_changed = pyqtSignal(int)
    gain_changed = pyqtSignal(float)
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

        cc = self.camera_controls
        cc.camera_selected.connect(self.camera_selected)
        cc.resolution_selected.connect(self.resolution_selected)
        cc.exposure_changed.connect(self.exposure_changed)
        cc.gain_changed.connect(self.gain_changed)
        cc.auto_exposure_toggled.connect(self.auto_exposure_toggled)
        cc.roi_changed.connect(self.roi_changed)
        cc.roi_reset_requested.connect(self.roi_reset_requested)

        pc = self.plot_controls
        pc.x_axis_limits_changed.connect(self.x_axis_limits_changed)
        pc.y_axis_limits_changed.connect(self.y_axis_limits_changed)
        pc.export_plot_image_requested.connect(self.export_plot_image_requested)

    @pyqtSlot(dict)
    def update_camera_ui_from_properties(self, props: dict):
        log.debug(f"TopControlPanel received camera properties: {props}")
        self.camera_controls.update_camera_properties_ui(props)

    def disable_all_camera_controls(self):
        self.camera_controls.disable_all_controls()

    def update_connection_status(self, text: str, connected: bool):
        self.conn_lbl.setText(text)
        if connected:
            color = "#A3BE8C"
        elif "error" in text.lower() or "failed" in text.lower():
            color = "#BF616A"
        else:
            color = "#D6C832"
        self.conn_lbl.setStyleSheet(f"font-weight:bold;color:{color};")

    def update_prim_data(self, idx: int, t_dev: float, p_dev: float):
        self.idx_lbl.setText(str(idx))
        self.time_lbl.setText(f"{t_dev:.2f}")
        self.pres_lbl.setText(f"{p_dev:.2f} mmHg")

    @pyqtSlot(list)
    def update_camera_resolutions(self, modes: list):
        self.camera_controls.update_camera_resolutions_list(modes)
