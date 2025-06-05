# pressure_plot_widget.py
import os
import time
import bisect
import logging
import math

from PyQt5.QtWidgets import (
    QWidget,
    QSizePolicy,
    QVBoxLayout,
    QMessageBox,
    QFileDialog,
    QScrollBar,
)
from PyQt5.QtCore import Qt, pyqtSlot
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

from utils.config import PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX

log = logging.getLogger(__name__)


class PressurePlotWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Matplotlib canvas
        self.fig = Figure(facecolor="white", tight_layout=True)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor("white")
        self.ax.set_xlabel("Time (s)", fontsize=16, fontweight="bold")
        self.ax.set_ylabel("Pressure (mmHg)", fontsize=16, fontweight="bold")
        self.ax.tick_params(labelsize=10)
        for spine in self.ax.spines.values():
            spine.set_color("#D8DEE9")
        self.ax.grid(True, linestyle="--", alpha=0.7, color="lightgray")

        (self.line,) = self.ax.plot([], [], "-", lw=2, color="black")

        self.canvas = FigureCanvas(self.fig)
        layout.addWidget(self.canvas)

        # Scrollbar for manual X panning
        self.scrollbar = QScrollBar(Qt.Horizontal, self)
        self.scrollbar.hide()
        layout.addWidget(self.scrollbar)
        self.scrollbar.valueChanged.connect(self._on_scroll)

        # MODIFIED: Apply a simple stylesheet to the scrollbar for better visibility
        self.scrollbar.setStyleSheet(
            """
            QScrollBar:horizontal {
                border: 1px solid #C0C0C0;
                background: #F0F0F0;
                height: 12px;
                margin: 0px 20px 0 20px;
            }
            QScrollBar::handle:horizontal {
                background: #A0A0A0;
                min-width: 25px;
                border-radius: 6px;
            }
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal {
                background: none;
                width: 0px;
            }
            """
        )

        # Data storage
        self.times = []
        self.values = []

        # Auto-scroll toggle
        self.auto_scroll_enabled = True

    def _on_scroll(self, value):
        """Scroll callback – optional if you wire scrollbar to manual control"""
        pass  # You can expand this to scroll xlim based on scrollbar if desired

    def clear_plot(self):
        self.times.clear()
        self.values.clear()
        self.line.set_data([], [])
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw_idle()

    def update_plot_with_scroll(self, new_time, new_value):
        """Append new data and update the plot, respecting auto-scroll mode."""
        self.times.append(new_time)
        self.values.append(new_value)
        self.line.set_data(self.times, self.values)
        self.ax.relim()
        self.ax.autoscale_view(scaley=True)

        if self.auto_scroll_enabled:
            x_window = 10  # seconds to show
            self.ax.set_xlim(new_time - x_window, new_time)

        self.canvas.draw_idle()

    def enable_auto_scroll(self, enabled: bool):
        """Enable or disable auto-follow behavior on the x-axis."""
        self.auto_scroll_enabled = enabled
        if enabled and self.times:
            x_window = 10
            self.ax.set_xlim(self.times[-1] - x_window, self.times[-1])
            self.canvas.draw_idle()

    def set_y_axis_limits(self, y_min, y_max):
        self.ax.set_ylim(y_min, y_max)
        self.canvas.draw_idle()
