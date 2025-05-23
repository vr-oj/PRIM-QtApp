# plot_control_panel.py
from PyQt5.QtWidgets import (
    QGroupBox,
    QFormLayout,
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
)
from PyQt5.QtCore import pyqtSignal

from config import PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX

log = __import__("logging").getLogger(__name__)


class PlotControlPanel(QGroupBox):
    x_axis_limits_changed = pyqtSignal(float, float)
    y_axis_limits_changed = pyqtSignal(float, float)
    export_plot_image_requested = pyqtSignal()
    clear_plot_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Plot Controls", parent)

        layout = QFormLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(6)

        # X-axis controls
        self.auto_x_cb = QCheckBox("Auto-scale X")
        self.auto_x_cb.setChecked(True)
        layout.addRow(self.auto_x_cb)

        self.x_min = QDoubleSpinBox()
        self.x_max = QDoubleSpinBox()
        for spin in (self.x_min, self.x_max):
            spin.setDecimals(1)
            spin.setRange(-1e6, 1e6)
            spin.setEnabled(False)

        x_layout = QHBoxLayout()
        x_layout.addWidget(QLabel("Min:"))
        x_layout.addWidget(self.x_min)
        x_layout.addWidget(QLabel("Max:"))
        x_layout.addWidget(self.x_max)
        layout.addRow("X-Limits:", x_layout)

        # Y-axis controls
        self.auto_y_cb = QCheckBox("Auto-scale Y")
        self.auto_y_cb.setChecked(False)
        layout.addRow(self.auto_y_cb)

        self.y_min = QDoubleSpinBox()
        self.y_max = QDoubleSpinBox()
        for spin in (self.y_min, self.y_max):
            spin.setDecimals(1)
            spin.setRange(-1e6, 1e6)
        self.y_min.setValue(PLOT_DEFAULT_Y_MIN)
        self.y_max.setValue(PLOT_DEFAULT_Y_MAX)

        y_layout = QHBoxLayout()
        y_layout.addWidget(QLabel("Min:"))
        y_layout.addWidget(self.y_min)
        y_layout.addWidget(QLabel("Max:"))
        y_layout.addWidget(self.y_max)
        layout.addRow("Y-Limits:", y_layout)

        # Action buttons
        self.reset_btn = QPushButton("↺ Reset Zoom/View")
        self.export_img_btn = QPushButton("Export Plot Image")
        self.clear_plot_btn = QPushButton("Clear Plot Data")

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.reset_btn)
        btn_layout.addWidget(self.clear_plot_btn)
        btn_layout.addWidget(self.export_img_btn)
        layout.addRow(btn_layout)

        # Signal connections
        self.auto_x_cb.toggled.connect(self._on_auto_x_toggled)
        self.auto_y_cb.toggled.connect(self._on_auto_y_toggled)

        self.x_min.valueChanged.connect(self._emit_x_limits)
        self.x_max.valueChanged.connect(self._emit_x_limits)
        self.y_min.valueChanged.connect(self._emit_y_limits)
        self.y_max.valueChanged.connect(self._emit_y_limits)

        self.reset_btn.clicked.connect(lambda: self._reset_zoom())
        self.export_img_btn.clicked.connect(self.export_plot_image_requested)
        self.clear_plot_btn.clicked.connect(
            self.clear_plot_requested
        )  # Connect new button

    def _on_auto_x_toggled(self, checked: bool):
        self.x_min.setEnabled(not checked)
        self.x_max.setEnabled(not checked)
        if checked:  # If auto is re-enabled, reset limits to auto by emitting inf
            self.x_axis_limits_changed.emit(float("-inf"), float("inf"))

    def _on_auto_y_toggled(self, checked: bool):
        self.y_min.setEnabled(not checked)
        self.y_max.setEnabled(not checked)
        if checked:  # If auto is re-enabled, reset limits to auto by emitting inf
            self.y_axis_limits_changed.emit(float("-inf"), float("inf"))

    def _emit_x_limits(self):
        if not self.auto_x_cb.isChecked():
            self.x_axis_limits_changed.emit(self.x_min.value(), self.x_max.value())

    def _emit_y_limits(self):
        if not self.auto_y_cb.isChecked():
            self.y_axis_limits_changed.emit(self.y_min.value(), self.y_max.value())

    def _reset_zoom(self):
        # Trigger reset/view-reload action
        # This will make the plot widget re-evaluate its view based on auto settings
        self.x_axis_limits_changed.emit(float("-inf"), float("inf"))
        self.y_axis_limits_changed.emit(float("-inf"), float("inf"))

        # Re-check the auto checkboxes which will also disable manual limit spinboxes
        self.auto_x_cb.setChecked(True)
        self.auto_y_cb.setChecked(True)

        # Set Y spin boxes to default values when auto_y is re-enabled
        self.y_min.setValue(PLOT_DEFAULT_Y_MIN)
        self.y_max.setValue(PLOT_DEFAULT_Y_MAX)
