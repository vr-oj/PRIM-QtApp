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
        # Add a faint grid to the plot
        self.ax.grid(True, linestyle="--", alpha=0.7, color="lightgray")

        (self.line,) = self.ax.plot([], [], "-", lw=2, color="black")

        self.canvas = FigureCanvas(self.fig)
        layout.addWidget(self.canvas)

        # Scrollbar for manual X panning
        self.scrollbar = QScrollBar(Qt.Horizontal, self)
        self.scrollbar.hide()
        layout.addWidget(self.scrollbar)
        self.scrollbar.valueChanged.connect(self._on_scroll)

        # Apply a simple stylesheet to the scrollbar for better visibility
        self.scrollbar.setStyleSheet(
            """
            QScrollBar:horizontal {
                border: 1px solid #C0C0C0; /* Light border for the scrollbar itself */
                background: #F0F0F0;    /* Background of the scrollbar groove */
                height: 15px;           /* Height of the scrollbar */
                margin: 0px 20px 0 20px;/* Margins to make space for add/sub-line buttons if they were visible */
            }
            QScrollBar::handle:horizontal {
                background: #A0A0A0;    /* A medium gray for the handle */
                min-width: 20px;        /* Minimum width of the handle */
                border-radius: 5px;     /* Rounded corners for the handle */
                border: 1px solid #808080; /* Border for the handle */
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                /* Style for arrow buttons if you want them, currently not explicitly shown */
                /* border: 1px solid grey; background: #E0E0E0; width: 18px; */
                width: 0px; /* Hide standard arrow buttons by making them zero width */
                height: 0px;
                background: none;
                border: none;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: none; /* Background of the area where you click to page scroll */
            }
        """
        )

        # Data storage
        self.times = []
        self.pressures = []
        self.manual_xlim = None
        self.manual_ylim = (PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)
        self.ax.set_ylim(self.manual_ylim)

        # For “rolling window” behavior when auto_x is off:
        self._follow_latest = True
        self._window_width = None  # Will be set the moment auto_x is toggled off

        # Placeholder text
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

        # Hover Label
        self.hover_annotation = self.ax.annotate(
            "",
            xy=(0, 0),
            xytext=(15, 15),
            textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.4", fc="wheat", alpha=0.85),
            arrowprops=dict(
                arrowstyle="->", connectionstyle="arc3,rad=.2", color="black"
            ),
        )
        self.hover_annotation.set_visible(False)

        # Connect hover event
        self.canvas.mpl_connect("motion_notify_event", self._on_hover)

    def _update_placeholder(self, text=None):
        if text:
            self.line.set_data([], [])
            if self.hover_annotation.get_visible():
                self.hover_annotation.set_visible(False)
            if self.placeholder:
                self.placeholder.set_text(text)
                self.placeholder.set_visible(True)
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
                self.placeholder.set_visible(False)
        self.canvas.draw_idle()

    def _find_nearest_datapoint(self, x_coord):
        """Finds the nearest data point (time, pressure, index) to the given x_coord."""
        if not self.times:
            return None, None, -1

        idx = bisect.bisect_left(self.times, x_coord)

        if idx == 0:
            best_idx = 0
        elif idx == len(self.times):
            best_idx = len(self.times) - 1
        else:
            dist1 = abs(x_coord - self.times[idx - 1])
            dist2 = abs(x_coord - self.times[idx])
            if dist1 <= dist2:
                best_idx = idx - 1
            else:
                best_idx = idx

        return self.times[best_idx], self.pressures[best_idx], best_idx

    def _on_hover(self, event):
        """Handles mouse motion event to show data point information."""
        if (
            not self.times
            or (self.placeholder and self.placeholder.get_visible())
            or not self.line.get_visible()
        ):
            if self.hover_annotation.get_visible():
                self.hover_annotation.set_visible(False)
                self.canvas.draw_idle()
            return

        annotation_visible = self.hover_annotation.get_visible()
        needs_redraw = False

        if event.inaxes == self.ax:
            x_mouse, y_mouse = event.xdata, event.ydata
            target_x, target_y, _ = self._find_nearest_datapoint(x_mouse)

            if target_x is not None:
                self.hover_annotation.xy = (target_x, target_y)
                new_text = f"Time: {target_x:.2f} s\nPressure: {target_y:.2f} mmHg"

                if self.hover_annotation.get_text() != new_text:
                    self.hover_annotation.set_text(new_text)
                    needs_redraw = True

                if not annotation_visible:
                    self.hover_annotation.set_visible(True)
                    needs_redraw = True
            else:
                if annotation_visible:
                    self.hover_annotation.set_visible(False)
                    needs_redraw = True
        else:
            if annotation_visible:
                self.hover_annotation.set_visible(False)
                needs_redraw = True

        if needs_redraw:
            self.canvas.draw_idle()

    @pyqtSlot(float, float, bool, bool)
    def update_plot(self, t, p, auto_x, auto_y):
        # Remove placeholder on first data
        if not self.times and self.placeholder and self.placeholder.get_visible():
            self._update_placeholder(None)

        # Append new data
        self.times.append(t)
        self.pressures.append(p)
        self.line.set_data(self.times, self.pressures)

        current_xlim = self.ax.get_xlim()
        current_ylim = self.ax.get_ylim()

        # ─── X‐axis handling ─────────────────────────────────────────────────────
        if auto_x:
            # Clear manual window and hide scrollbar
            self.manual_xlim = None
            self._window_width = None
            self._follow_latest = True
            self.scrollbar.hide()

            if len(self.times) > 1:
                start, end = self.times[0], self.times[-1]
                pad = max(1, (end - start) * 0.05)
                self.ax.set_xlim(start - pad * 0.1, end + pad * 0.9)
            elif self.times:
                t0 = self.times[-1]
                self.ax.set_xlim(t0 - 0.5, t0 + 0.5)

        else:
            # If first time turning off auto_x, capture window width:
            if self._window_width is None:
                x0, x1 = self.ax.get_xlim()
                self._window_width = x1 - x0
                self._follow_latest = True
                if self.times:
                    t_last = self.times[-1]
                    new_x0 = max(self.times[0], t_last - self._window_width)
                    new_x1 = t_last
                    self.manual_xlim = (new_x0, new_x1)
                    self.ax.set_xlim(self.manual_xlim)
                    self._update_scrollbar()

            else:
                if self._follow_latest:
                    # Follow latest
                    t_last = self.times[-1]
                    new_x1 = t_last
                    new_x0 = max(self.times[0], new_x1 - self._window_width)
                    self.manual_xlim = (new_x0, new_x1)
                    self.ax.set_xlim(self.manual_xlim)
                    self._update_scrollbar()
                else:
                    # User has scrolled back; respect manual_xlim
                    if self.manual_xlim:
                        self.ax.set_xlim(self.manual_xlim)
                        self._update_scrollbar()

        # ─── Y‐axis handling ─────────────────────────────────────────────────────
        if auto_y:
            self.manual_ylim = None
            if self.pressures:
                mn, mx = min(self.pressures), max(self.pressures)
                pad = max(abs(mx - mn) * 0.1, 2.0)
                self.ax.set_ylim(mn - pad, mx + pad)
        else:
            if self.manual_ylim:
                self.ax.set_ylim(self.manual_ylim)
            elif not self.pressures:
                self.ax.set_ylim(PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)

        new_xlim = self.ax.get_xlim()
        new_ylim = self.ax.get_ylim()

        if current_xlim != new_xlim or current_ylim != new_ylim or self.line.stale:
            self.canvas.draw_idle()

    def _update_scrollbar(self):
        if not self.times or not self.manual_xlim:
            self.scrollbar.hide()
            return

        xmin, xmax = self.manual_xlim
        idx0 = bisect.bisect_left(self.times, xmin)
        idx1 = bisect.bisect_right(self.times, xmax)
        window_size = max(idx1 - idx0, 1)
        full_len = len(self.times)

        if full_len <= window_size:
            self.scrollbar.hide()
            return

        self.scrollbar.setMinimum(0)
        self.scrollbar.setMaximum(max(full_len - window_size, 0))
        self.scrollbar.setPageStep(window_size)
        self.scrollbar.setSingleStep(max(window_size // 10, 1))
        self.scrollbar.setValue(idx0)
        self.scrollbar.show()

    @pyqtSlot(int)
    def _on_scroll(self, pos):
        if not self.manual_xlim or not self.times or len(self.times) <= 1:
            return

        window_indices = self.scrollbar.pageStep()
        start_idx = pos
        end_idx = min(start_idx + window_indices - 1, len(self.times) - 1)

        if start_idx >= end_idx and len(self.times) > 1:
            start_idx = max(0, len(self.times) - 2)
            end_idx = len(self.times) - 1

        if start_idx < 0:
            start_idx = 0

        xmin_new = self.times[start_idx]
        xmax_new = self.times[end_idx]

        if xmin_new == xmax_new and len(self.times) > 1:
            if end_idx + 1 < len(self.times):
                xmax_new = self.times[end_idx + 1]
            elif start_idx - 1 >= 0:
                xmin_new = self.times[start_idx - 1]
            else:
                xmax_new = xmin_new + 1.0

        self.manual_xlim = (xmin_new, xmax_new)
        self.ax.set_xlim(self.manual_xlim)
        self.canvas.draw_idle()

        # If the user scrolled away from the rightmost edge, pause following
        total_points = len(self.times)
        if pos + window_indices - 1 < total_points - 1:
            self._follow_latest = False
        else:
            # If scrolled all the way to the right, resume follow mode
            self._follow_latest = True

    def set_manual_x_limits(self, xmin, xmax):
        if xmin < xmax:
            self.manual_xlim = (xmin, xmax)
            self.ax.set_xlim(self.manual_xlim)
            self._follow_latest = (
                False  # Pause following when user explicitly sets limits
            )
            self._update_scrollbar()
            self.canvas.draw_idle()
        else:
            log.warning("X min must be less than X max")

    def set_manual_y_limits(self, ymin, ymax):
        if ymin < ymax and math.isfinite(ymin) and math.isfinite(ymax):
            self.manual_ylim = (ymin, ymax)
            self.ax.set_ylim(self.manual_ylim)
            self.canvas.draw_idle()
        else:
            log.warning(
                f"Y limits must be finite and min < max. Received: {ymin}, {ymax}"
            )

    def reset_zoom(self, auto_x, auto_y):
        self.manual_xlim = None
        if auto_x:
            self._window_width = None
            self._follow_latest = True
            self.scrollbar.hide()
        else:
            x0, x1 = self.ax.get_xlim()
            self._window_width = x1 - x0
            self._follow_latest = True
            if self.times:
                t_last = self.times[-1]
                new_x0 = max(self.times[0], t_last - self._window_width)
                new_x1 = t_last
                self.manual_xlim = (new_x0, new_x1)
                self.ax.set_xlim(self.manual_xlim)
                self._update_scrollbar()

        if auto_y:
            self.manual_ylim = None
        else:
            self.manual_ylim = (PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)
            self.ax.set_ylim(self.manual_ylim)

        # Re-draw with the last known data point (if any) to enforce scaling
        if self.times:
            self.update_plot(self.times[-1], self.pressures[-1], auto_x, auto_y)
        else:
            # No data: set defaults
            self.ax.set_xlim(0, 10)
            if not auto_y:
                self.ax.set_ylim(self.manual_ylim)
            self._update_placeholder("Plot cleared or waiting for data.")
            self.canvas.draw_idle()

    def clear_plot(self):
        self.times.clear()
        self.pressures.clear()

        self.line.set_data([], [])
        self.ax.set_xlim(0, 100)

        if self.manual_ylim is None:
            self.ax.set_ylim(PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)
        elif (
            isinstance(self.manual_ylim, tuple)
            and len(self.manual_ylim) == 2
            and all(v is not None and math.isfinite(v) for v in self.manual_ylim)
        ):
            self.ax.set_ylim(self.manual_ylim)
        else:
            self.manual_ylim = (PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)
            self.ax.set_ylim(self.manual_ylim)

        if self.hover_annotation.get_visible():
            self.hover_annotation.set_visible(False)

        self._update_placeholder("Plot data cleared.")

    def export_as_image(self):
        if not self.times and not (self.placeholder and self.placeholder.get_visible()):
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
            hover_visible = self.hover_annotation.get_visible()
            placeholder_text_visible = (
                self.placeholder and self.placeholder.get_visible()
            )

            if hover_visible:
                self.hover_annotation.set_visible(False)
            if placeholder_text_visible:
                self.placeholder.set_visible(False)

            self.canvas.draw()
            self.fig.savefig(path, dpi=300, facecolor=self.fig.get_facecolor())

            if hover_visible:
                self.hover_annotation.set_visible(True)
            if placeholder_text_visible:
                self.placeholder.set_visible(True)

            self.canvas.draw_idle()

            sb = self.window().statusBar() if self.window() else None
            if sb:
                sb.showMessage(f"Plot exported to {os.path.basename(path)}", 3000)
        except Exception as e:
            log.exception(f"Error exporting plot image: {e}")
            QMessageBox.critical(
                self, "Export Error", f"Could not save plot image: {e}"
            )
