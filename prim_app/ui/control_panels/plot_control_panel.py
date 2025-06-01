# prim_app/ui/control_panels/plot_control_panel.py

import logging
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

from utils.config import PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX

log = logging.getLogger(__name__)


class PlotControlPanel(QGroupBox):
    """
    Panel with controls for the live plot (Pressure vs. Time).
    """

    # Signals that MainWindow expects to connect:
    autoscale_x_changed = pyqtSignal(bool)
    autoscale_y_changed = pyqtSignal(bool)
    x_axis_limits_changed = pyqtSignal(float, float)
    y_axis_limits_changed = pyqtSignal(float, float)
    reset_zoom_requested = pyqtSignal()
    export_plot_image_requested = pyqtSignal()
    clear_plot_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Plot Controls", parent)

        layout = QFormLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(4)

        # ─── X‐axis auto‐scale checkbox ────────────────────────────────────────
        self.auto_x_cb = QCheckBox("Auto‐scale X")
        self.auto_x_cb.setChecked(True)
        layout.addRow(self.auto_x_cb)

        # X‐limits spin boxes (disabled until auto‐scale is unchecked)
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
        layout.addRow("X‐Limits:", x_layout)

        # ─── Y‐axis auto‐scale checkbox ────────────────────────────────────────
        self.auto_y_cb = QCheckBox("Auto‐scale Y")
        self.auto_y_cb.setChecked(False)
        layout.addRow(self.auto_y_cb)

        # Y‐limits spin boxes (enabled by default, since auto‐scale Y is unchecked)
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
        layout.addRow("Y‐Limits:", y_layout)

        # ─── Action buttons: Reset Zoom, Clear Data, Export Image ────────────
        self.reset_btn = QPushButton("↺ Reset Zoom/View")
        self.clear_plot_btn = QPushButton("Clear Plot Data")
        self.export_img_btn = QPushButton("Export Plot Image")

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.reset_btn)
        btn_layout.addWidget(self.clear_plot_btn)
        btn_layout.addWidget(self.export_img_btn)
        layout.addRow(btn_layout)

        # ─── Connect widget events to our signals ────────────────────────────
        # Auto‐scale toggles
        self.auto_x_cb.toggled.connect(self._on_auto_x_toggled)
        self.auto_x_cb.toggled.connect(self.autoscale_x_changed.emit)

        self.auto_y_cb.toggled.connect(self._on_auto_y_toggled)
        self.auto_y_cb.toggled.connect(self.autoscale_y_changed.emit)

        # X‐limits spin changes
        self.x_min.valueChanged.connect(self._emit_x_limits)
        self.x_max.valueChanged.connect(self._emit_x_limits)

        # Y‐limits spin changes
        self.y_min.valueChanged.connect(self._emit_y_limits)
        self.y_max.valueChanged.connect(self._emit_y_limits)

        # Reset Zoom button
        self.reset_btn.clicked.connect(self.reset_zoom_requested.emit)

        # Clear Plot button
        self.clear_plot_btn.clicked.connect(self.clear_plot_requested.emit)

        # Export Plot Image button
        self.export_img_btn.clicked.connect(self.export_plot_image_requested.emit)

    def _on_auto_x_toggled(self, checked: bool):
        """
        Enable/disable X‐limits spin boxes based on Auto‐scale X state.
        """
        self.x_min.setEnabled(not checked)
        self.x_max.setEnabled(not checked)

    def _on_auto_y_toggled(self, checked: bool):
        """
        Enable/disable Y‐limits spin boxes based on Auto‐scale Y state.
        """
        self.y_min.setEnabled(not checked)
        self.y_max.setEnabled(not checked)

    def _emit_x_limits(self):
        """
        Emit x_axis_limits_changed if Auto‐scale X is off.
        """
        if not self.auto_x_cb.isChecked():
            self.x_axis_limits_changed.emit(self.x_min.value(), self.x_max.value())

    def _emit_y_limits(self):
        """
        Emit y_axis_limits_changed if Auto‐scale Y is off.
        """
        if not self.auto_y_cb.isChecked():
            self.y_axis_limits_changed.emit(self.y_min.value(), self.y_max.value())

    def is_autoscale_x(self) -> bool:
        """
        Return True if Auto‐scale X is checked.
        """
        return self.auto_x_cb.isChecked()

    def is_autoscale_y(self) -> bool:
        """
        Return True if Auto‐scale Y is checked.
        """
        return self.auto_y_cb.isChecked()

    def setEnabled(self, enabled: bool):
        """
        Override setEnabled so that disabling also greys out children appropriately.
        """
        super().setEnabled(enabled)
        self.auto_x_cb.setEnabled(enabled)
        self.auto_y_cb.setEnabled(enabled)
        self.x_min.setEnabled(enabled and not self.auto_x_cb.isChecked())
        self.x_max.setEnabled(enabled and not self.auto_x_cb.isChecked())
        self.y_min.setEnabled(enabled and not self.auto_y_cb.isChecked())
        self.y_max.setEnabled(enabled and not self.auto_y_cb.isChecked())
        self.reset_btn.setEnabled(enabled)
        self.clear_plot_btn.setEnabled(enabled)
        self.export_img_btn.setEnabled(enabled)
