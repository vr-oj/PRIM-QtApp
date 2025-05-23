import logging

from PyQt5.QtWidgets import (
    QWidget,
    QGroupBox,
    QHBoxLayout,
    QFormLayout,
    QLabel,
)
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot

from .plot_control_panel import PlotControlPanel

log = logging.getLogger(__name__)


class TopControlPanel(QWidget):
    """
    Composite panel combining camera controls, device status, and plot controls.
    """

    # generic passthrough
    parameter_changed = pyqtSignal(str, object)

    # plot signals…
    x_axis_limits_changed = pyqtSignal(float, float)
    y_axis_limits_changed = pyqtSignal(float, float)
    export_plot_image_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # Layout
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 2, 5, 2)
        layout.setSpacing(10)

        # PRIM Device status box
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

        # Plot control panel
        self.plot_controls = PlotControlPanel(self)
        layout.addWidget(self.plot_controls, 1)

        # Forward plot signals
        self.plot_controls.x_axis_limits_changed.connect(self.x_axis_limits_changed)
        self.plot_controls.y_axis_limits_changed.connect(self.y_axis_limits_changed)
        self.plot_controls.export_plot_image_requested.connect(
            self.export_plot_image_requested
        )

    def update_connection_status(self, text: str, connected: bool):
        """
        Show connection status (with color coding).
        """
        self.conn_lbl.setText(text)
        if connected:
            color = "#A3BE8C"
        elif "error" in text.lower() or "failed" in text.lower():
            color = "#BF616A"
        else:
            color = "#D6C832"
        self.conn_lbl.setStyleSheet(f"font-weight:bold;color:{color};")

    def update_prim_data(self, idx: int, t_dev: float, p_dev: float):
        """
        Update the frame index, device time, and pressure readout.
        """
        self.idx_lbl.setText(str(idx))
        self.time_lbl.setText(f"{t_dev:.2f}")
        self.pres_lbl.setText(f"{p_dev:.2f} mmHg")
