"""Main window for pressure-only PRIM app."""

import os
import logging
import csv

from PyQt5.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QComboBox,
    QAction,
    QFileDialog,
    QMessageBox,
    QToolBar,
    QStatusBar,
    QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QIcon

import utils.config as config
from utils.config import APP_NAME, APP_VERSION, ABOUT_TEXT, set_results_dir
from utils.path_helpers import resource_path
from utils.utils import list_serial_ports, timestamped_filename
from ui.control_panels.top_control_panel import TopControlPanel
from ui.control_panels.plot_control_panel import PlotControlPanel
from ui.canvas.pressure_plot_widget import PressurePlotWidget
from threads.serial_thread import SerialThread
from pressure_recorder import PressureCsvRecorder

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # State
        self._serial_thread: SerialThread = None
        self._recorder = PressureCsvRecorder()

        # Icons
        self._init_icons()

        # UI
        self._build_ui()
        self._build_toolbar()
        self._build_menus()
        self.setStatusBar(QStatusBar(self))

        # Init
        self._refresh_ports()
        self._set_initial_states()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(480, 320)
        self.resize(1100, 700)

    # ---------------- UI -----------------
    def _init_icons(self):
        base = resource_path("ui", "icons")

        def ico(name):
            p = os.path.join(base, name)
            return QIcon(p) if os.path.exists(p) else QIcon()

        self.icon_connect = ico("plug.svg")
        self.icon_disconnect = ico("plug_disconnect.svg")
        self.icon_record_start = ico("record.svg")
        self.icon_record_stop = ico("stop.svg")
        self.icon_refresh = ico("sync.svg")
        self.icon_csv = ico("csv.svg")
        self.icon_controls = ico("settings.svg")

    def _build_ui(self):
        central = QWidget(self)
        v = QVBoxLayout(central)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(8)

        # Top row: Serial connection | PRIM status | Plot controls
        top = QWidget(self)
        self.top_ribbon = top
        top_lay = QHBoxLayout(top)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.setSpacing(8)

        # Serial connection group
        ser_group = QGroupBox("Arduino Connection", self)
        ser_form = QFormLayout(ser_group)
        ser_form.setContentsMargins(6, 6, 6, 6)
        self.port_combo = QComboBox()
        self.btn_refresh_ports = QPushButton(self.icon_refresh, "Refresh")
        self.btn_connect = QPushButton(self.icon_connect, "Connect")
        self.btn_refresh_ports.clicked.connect(self._refresh_ports)
        self.btn_connect.clicked.connect(self._toggle_serial)
        ser_row = QWidget()
        ser_row_lay = QHBoxLayout(ser_row)
        ser_row_lay.setContentsMargins(0, 0, 0, 0)
        ser_row_lay.setSpacing(6)
        ser_row_lay.addWidget(self.port_combo)
        ser_row_lay.addWidget(self.btn_refresh_ports)
        ser_row_lay.addWidget(self.btn_connect)
        ser_form.addRow("Serial Port:", ser_row)

        # PRIM device status/controls
        self.top_ctrl = TopControlPanel(self)
        self.top_ctrl.zero_requested.connect(self._on_zero_prim)

        # Plot controls
        self.plot_ctrl = PlotControlPanel(self)

        top_lay.addWidget(ser_group, 2)
        top_lay.addWidget(self.top_ctrl, 2)
        top_lay.addWidget(self.plot_ctrl, 2)
        v.addWidget(top, 0)

        # Plot area
        self.pressure_plot = PressurePlotWidget(self)
        self.pressure_plot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        v.addWidget(self.pressure_plot, 1)

        # Wire plot control signals used by widget
        if hasattr(self.pressure_plot, "set_manual_x_limits"):
            self.plot_ctrl.x_axis_limits_changed.connect(
                self.pressure_plot.set_manual_x_limits
            )
        if hasattr(self.pressure_plot, "set_manual_y_limits"):
            self.plot_ctrl.y_axis_limits_changed.connect(
                self.pressure_plot.set_manual_y_limits
            )
        if hasattr(self.pressure_plot, "reset_zoom"):
            self.plot_ctrl.reset_zoom_requested.connect(
                lambda: self.pressure_plot.reset_zoom(
                    self.plot_ctrl.is_autoscale_x(), self.plot_ctrl.is_autoscale_y()
                )
            )
        if hasattr(self.pressure_plot, "export_as_image"):
            self.plot_ctrl.export_plot_image_requested.connect(
                self.pressure_plot.export_as_image
            )
        if hasattr(self.pressure_plot, "clear_plot"):
            self.plot_ctrl.clear_plot_requested.connect(self.pressure_plot.clear_plot)

        self.setCentralWidget(central)

    def _build_toolbar(self):
        tb = QToolBar("Main", self)
        self.addToolBar(tb)

        self.act_refresh = QAction(self.icon_refresh, "Refresh Ports", self)
        self.act_refresh.triggered.connect(self._refresh_ports)
        tb.addAction(self.act_refresh)

        self.act_connect = QAction(self.icon_connect, "Connect PRIM", self)
        self.act_connect.triggered.connect(self._toggle_serial)
        tb.addAction(self.act_connect)

        tb.addSeparator()

        self.act_start_csv = QAction(self.icon_record_start, "Start CSV Save", self)
        self.act_start_csv.triggered.connect(self._start_csv_save)
        tb.addAction(self.act_start_csv)

        self.act_stop_csv = QAction(self.icon_record_stop, "Stop CSV Save", self)
        self.act_stop_csv.triggered.connect(self._stop_csv_save)
        tb.addAction(self.act_stop_csv)

        tb.addSeparator()

        # View toggles
        self.act_show_controls = QAction(self.icon_controls, "Hide Controls", self)
        self.act_show_controls.setCheckable(True)
        self.act_show_controls.setChecked(True)
        self.act_show_controls.toggled.connect(self._toggle_controls)
        tb.addAction(self.act_show_controls)

        self.act_always_on_top = QAction("Always on Top", self)
        self.act_always_on_top.setCheckable(True)
        self.act_always_on_top.toggled.connect(self._toggle_always_on_top)
        tb.addAction(self.act_always_on_top)

    def _build_menus(self):
        menubar = self.menuBar()
        filem = menubar.addMenu("File")
        act_export_data = QAction(self.icon_csv, "Export Plot Data as CSV", self)
        act_export_data.triggered.connect(self._export_plot_data_as_csv)
        filem.addAction(act_export_data)

        act_results = QAction("Choose Results Folder…", self)
        act_results.triggered.connect(self._choose_results_dir)
        filem.addAction(act_results)

        filem.addSeparator()
        act_exit = QAction("Exit", self)
        act_exit.triggered.connect(self.close)
        filem.addAction(act_exit)

        viewm = menubar.addMenu("View")
        viewm.addAction(self.act_show_controls)
        viewm.addAction(self.act_always_on_top)

        helpm = menubar.addMenu("Help")
        act_about = QAction("About", self)
        act_about.triggered.connect(self._show_about)
        helpm.addAction(act_about)

    # ------------- Behavior --------------
    def _set_initial_states(self):
        self._update_connect_ui(False)
        self._update_csv_actions()

    def _update_connect_ui(self, connected: bool):
        if connected:
            self.act_connect.setIcon(self.icon_disconnect)
            self.act_connect.setText("Disconnect PRIM")
            self.btn_connect.setIcon(self.icon_disconnect)
            self.btn_connect.setText("Disconnect")
            self.port_combo.setEnabled(False)
        else:
            self.act_connect.setIcon(self.icon_connect)
            self.act_connect.setText("Connect PRIM")
            self.btn_connect.setIcon(self.icon_connect)
            self.btn_connect.setText("Connect")
            self.port_combo.setEnabled(True)

    def _update_csv_actions(self):
        active = self._recorder.is_active
        self.act_start_csv.setEnabled(not active)
        self.act_stop_csv.setEnabled(active)

    @pyqtSlot(bool)
    def _toggle_controls(self, show: bool):
        if hasattr(self, "top_ribbon") and self.top_ribbon is not None:
            self.top_ribbon.setVisible(show)
            # Keep action text intuitive
            self.act_show_controls.setText("Hide Controls" if show else "Show Controls")

    @pyqtSlot(bool)
    def _toggle_always_on_top(self, enabled: bool):
        try:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
            # Re-apply flags
            self.show()
        except Exception:
            log.exception("Failed toggling Always on Top")

    @pyqtSlot()
    def _refresh_ports(self):
        self.port_combo.clear()
        self.port_combo.addItem("Select port…", None)
        for dev, desc in list_serial_ports():
            label = f"{dev} — {desc}"
            self.port_combo.addItem(label, dev)

    @pyqtSlot()
    def _toggle_serial(self):
        # Disconnect if running
        if self._serial_thread and self._serial_thread.isRunning():
            try:
                self._serial_thread.stop()
            except Exception:
                log.exception("Error stopping serial thread")
            self._serial_thread = None
            self.top_ctrl.update_connection_status("Disconnected", False)
            self.statusBar().showMessage("Serial disconnected", 3000)
            self._update_connect_ui(False)
            return

        # Connect
        port = self.port_combo.currentData()
        if not port:
            QMessageBox.warning(self, "Serial", "Please select a serial port.")
            return
        self._serial_thread = SerialThread(port=port, parent=self)
        self._serial_thread.data_ready.connect(self._on_serial_data)
        self._serial_thread.status_changed.connect(self._on_serial_status)
        self._serial_thread.error_occurred.connect(self._on_serial_error)
        self._serial_thread.start()
        self._update_connect_ui(True)

    @pyqtSlot(int, float, float)
    def _on_serial_data(self, frame_idx: int, t_dev: float, p: float):
        # Update UI
        self.top_ctrl.update_prim_data(frame_idx, t_dev, p)
        # Update plot using PlotControlPanel states
        self.pressure_plot.update_plot(
            t_dev, p, self.plot_ctrl.is_autoscale_x(), self.plot_ctrl.is_autoscale_y()
        )
        # Append to CSV if active
        if self._recorder.is_active:
            self._recorder.append(frame_idx, t_dev, p)

    @pyqtSlot(str)
    def _on_serial_status(self, text: str):
        connected = "Connected" in text or "Reconnected" in text
        self.top_ctrl.update_connection_status(text, connected)
        self.statusBar().showMessage(text, 3000)

    @pyqtSlot(str)
    def _on_serial_error(self, msg: str):
        self.top_ctrl.update_connection_status(msg, False)
        QMessageBox.critical(self, "Serial Error", msg)
        self._update_connect_ui(False)

    @pyqtSlot()
    def _on_zero_prim(self):
        # Clear plot and send 'Z' if connected
        try:
            self.pressure_plot.clear_plot()
            if self._serial_thread and self._serial_thread.isRunning():
                self._serial_thread.send_command("Z")
                self.statusBar().showMessage("Sent zero command to PRIM.", 3000)
            else:
                self.statusBar().showMessage("PRIM not connected; plot cleared.", 3000)
        except Exception:
            log.exception("Failed to send zero command")

    # ---------- CSV saving / export ----------
    @pyqtSlot()
    def _start_csv_save(self):
        if self._recorder.is_active:
            return
        default_name = timestamped_filename("pressure", "csv")
        default_path = os.path.join(config.PRIM_RESULTS_DIR, default_name)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save pressure CSV", default_path, "CSV Files (*.csv)"
        )
        if not path:
            return
        try:
            self._recorder.start(path)
            self.statusBar().showMessage(f"Saving CSV → {path}", 3000)
        except Exception as e:
            log.exception("Failed to start CSV recording")
            QMessageBox.critical(self, "CSV Error", str(e))
        self._update_csv_actions()

    @pyqtSlot()
    def _stop_csv_save(self):
        if not self._recorder.is_active:
            return
        out = self._recorder.stop()
        self.statusBar().showMessage(f"Saved CSV: {out}", 5000)
        self._update_csv_actions()

    def _export_plot_data_as_csv(self):
        data = self.pressure_plot.get_plot_data()
        if not data["time"]:
            QMessageBox.information(self, "Export CSV", "No data to export.")
            return
        default_path = os.path.join(
            config.PRIM_RESULTS_DIR, timestamped_filename("plot_data", "csv")
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Export plot data as CSV", default_path, "CSV Files (*.csv)"
        )
        if not path:
            return
        try:
            with open(path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["Time (s)", "Pressure (mmHg)"])
                for t, p in zip(data["time"], data["pressure"]):
                    w.writerow([t, p])
            self.statusBar().showMessage(f"Exported CSV: {path}", 4000)
        except Exception as e:
            log.exception("Export CSV error")
            QMessageBox.critical(self, "Export Error", str(e))

    def _choose_results_dir(self):
        new_dir = QFileDialog.getExistingDirectory(
            self, "Select Results Folder", config.PRIM_RESULTS_DIR
        )
        if new_dir:
            set_results_dir(new_dir)
            self.statusBar().showMessage(f"Results folder → {new_dir}", 4000)

    def _show_about(self):
        QMessageBox.information(self, f"About {APP_NAME}", ABOUT_TEXT)
