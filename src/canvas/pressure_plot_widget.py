import os
import time
import logging

from PyQt5.QtWidgets import (
    QWidget,
    QSizePolicy,
    QVBoxLayout,
    QMessageBox,
    QFileDialog,
)
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

from config import PLOT_MAX_POINTS, PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX

log = logging.getLogger(__name__)


class PressurePlotWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.fig = Figure(facecolor="white", tight_layout=True)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor("white")
        self.ax.set_xlabel("Time (s)", fontsize=12, fontweight="bold")
        self.ax.set_ylabel("Pressure (mmHg)", fontsize=12, fontweight="bold")
        self.ax.tick_params(labelsize=8)
        for spine in self.ax.spines.values():
            spine.set_color("#D8DEE9")
        (self.line,) = self.ax.plot([], [], "-", lw=2, color="black")

        self.canvas = FigureCanvas(self.fig)
        layout.addWidget(self.canvas)

        self.times = []
        self.pressures = []
        self.max_pts = PLOT_MAX_POINTS
        self.manual_xlim = None
        self.manual_ylim = (PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)
        self.ax.set_ylim(self.manual_ylim)

        self.placeholder = self.ax.text(
            0.5,
            0.5,
            "Waiting for PRIM device data...",
            transform=self.ax.transAxes,
            ha="center",
            va="center",
            fontsize=12,
            color="gray",
            bbox=dict(boxstyle="round,pad=0.5", fc="#ECEFF4", alpha=0.8),
        )

    def _update_placeholder(self, text=None):
        if text:
            self.line.set_data([], [])
            if self.placeholder:
                self.placeholder.set_text(text)
            else:
                self.placeholder = self.ax.text(
                    0.5,
                    0.5,
                    text,
                    transform=self.ax.transAxes,
                    ha="center",
                    va="center",
                    fontsize=12,
                    color="gray",
                    bbox=dict(boxstyle="round,pad=0.5", fc="#ECEFF4", alpha=0.8),
                )
        else:
            if self.placeholder:
                self.placeholder.remove()
                self.placeholder = None
        self.canvas.draw_idle()

    def update_plot(self, t, p, auto_x, auto_y):
        if not self.times:
            self._update_placeholder(None)

        self.times.append(t)
        self.pressures.append(p)
        if len(self.times) > self.max_pts:
            self.times = self.times[-self.max_pts :]
            self.pressures = self.pressures[-self.max_pts :]

        self.line.set_data(self.times, self.pressures)

        if auto_x:
            if len(self.times) > 1:
                start, end = self.times[0], self.times[-1]
                pad = max(1, (end - start) * 0.05)
                self.ax.set_xlim(start - pad * 0.1, end + pad * 0.9)
            else:
                t0 = self.times[-1]
                self.ax.set_xlim(t0 - 0.5, t0 + 0.5)
            self.manual_xlim = None
        elif self.manual_xlim:
            self.ax.set_xlim(self.manual_xlim)

        if auto_y:
            mn, mx = min(self.pressures), max(self.pressures)
            pad = max(abs(mx - mn) * 0.1, 2.0)
            self.ax.set_ylim(mn - pad, mx + pad)
            self.manual_ylim = None
        elif self.manual_ylim:
            self.ax.set_ylim(self.manual_ylim)

        self.canvas.draw_idle()

    def set_manual_x_limits(self, xmin, xmax):
        if xmin < xmax:
            self.manual_xlim = (xmin, xmax)
            self.ax.set_xlim(self.manual_xlim)
            self.canvas.draw_idle()
        else:
            log.warning("X min must be less than X max")

    def set_manual_y_limits(self, ymin, ymax):
        if ymin < ymax:
            self.manual_ylim = (ymin, ymax)
            self.ax.set_ylim(self.manual_ylim)
            self.canvas.draw_idle()
        else:
            log.warning("Y min must be less than Y max")

    def reset_zoom(self, auto_x, auto_y):
        self.manual_xlim = None
        if not auto_y:
            self.manual_ylim = (PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)
            self.ax.set_ylim(self.manual_ylim)
        else:
            self.manual_ylim = None

        if self.times:
            self.update_plot(self.times[-1], self.pressures[-1], auto_x, auto_y)
        else:
            self.ax.set_xlim(0, 10)
            if not auto_y:
                self.ax.set_ylim(self.manual_ylim)
            else:
                self.ax.autoscale(enable=True, axis="y")
            self._update_placeholder("Plot cleared or waiting for data.")
        self.canvas.draw_idle()

    def clear_plot(self):
        self.times.clear()
        self.pressures.clear()
        self.line.set_data([], [])
        self.ax.set_xlim(0, 10)
        if self.manual_ylim:
            self.ax.set_ylim(self.manual_ylim)
        else:
            self.ax.set_ylim(PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)
        self._update_placeholder("Plot data cleared.")
        self.canvas.draw_idle()

    def export_as_image(self):
        if not self.times and not self.placeholder:
            QMessageBox.warning(self, "Empty Plot", "Plot has no data to export.")
            return
        default_name = f"plot_export_{time.strftime('%Y%m%d-%H%M%S')}.png"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Plot Image",
            default_name,
            "PNG (*.png);;JPEG (*.jpg);;SVG (*.svg);;PDF (*.pdf)",
        )
        if not path:
            return
        try:
            visible = bool(self.placeholder)
            if visible:
                self.placeholder.set_visible(False)
            self.fig.savefig(path, dpi=300, facecolor=self.fig.get_facecolor())
            if visible and self.placeholder:
                self.placeholder.set_visible(True)
            sb = self.window().statusBar() if self.window() else None
            if sb:
                sb.showMessage(f"Plot exported to {os.path.basename(path)}", 3000)
        except Exception:
            log.exception("Error exporting plot image")
            QMessageBox.critical(self, "Export Error", "Could not save plot image")
