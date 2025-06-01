# prim_app/main_window.py

import os
import sys
import re
import logging
import csv
import json  # Keep for other potential uses

from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QDockWidget,
    QTextEdit,
    QToolBar,
    QStatusBar,
    QAction,
    QFileDialog,
    QDialog,
    QFormLayout,
    QDialogButtonBox,
    QLineEdit,
    QComboBox,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QSplitter,
    QMessageBox,
    QSizePolicy,
    QTabWidget,
    QGroupBox,
    QFormLayout,
    QPushButton,
    QCheckBox,
)
from PyQt5.QtCore import Qt, pyqtSlot, QTimer, QVariant, QDateTime, QSize
from PyQt5.QtGui import QIcon, QKeySequence

import prim_app

from utils.app_settings import (
    save_app_setting,
    load_app_setting,
    SETTING_LAST_CAMERA_INDEX,
)
from utils.config import (
    DEFAULT_FPS,
    DEFAULT_FRAME_SIZE,
    APP_NAME,
    APP_VERSION,
    PRIM_RESULTS_DIR,
    DEFAULT_VIDEO_EXTENSION,
    DEFAULT_VIDEO_CODEC,
    ABOUT_TEXT,
    # CAMERA_HARDCODED_DEFAULTS,  # Temporarily removed
)

from ui.control_panels.top_control_panel import TopControlPanel
from ui.control_panels.camera_control_panel import CameraControlPanel
from ui.canvas.qtcamera_widget import QtCameraWidget
from ui.canvas.pressure_plot_widget import PressurePlotWidget
from threads.sdk_camera_thread import SDKCameraThread
from threads.serial_thread import SerialThread

from recording import RecordingWorker
from utils.utils import list_serial_ports

log = logging.getLogger(__name__)


def snake_case(name: str) -> str:
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).upper()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # ─── State variables ─────────────────────────────────────────────────────
        self._serial_thread = None
        self._recording_worker = None
        self._is_recording = False

        # So keep these as None for now:
        self.camera_thread = None
        self.camera_panel = None
        self.camera_view = None

        self.camera_settings = {}
        self.last_trial_basepath = None

        # ─── Build UI scaffolding ────────────────────────────────────────────────
        self._init_paths_and_icons()
        self._build_console_log_dock()

        # ─── Build the central widget / layouts (including the new camera widget) ─
        self._build_central_widget_layout()

        # ─── Build menus, toolbars, status bar ───────────────────────────────────
        self._build_menus()
        self._build_main_toolbar()
        self._build_status_bar()

        # ─── Hook up top‐control signals for the plotting widget ─────────────────
        self.top_ctrl.x_axis_limits_changed.connect(
            self.pressure_plot_widget.set_manual_x_limits
        )
        self.top_ctrl.y_axis_limits_changed.connect(
            self.pressure_plot_widget.set_manual_y_limits
        )
        self.top_ctrl.export_plot_image_requested.connect(
            self.pressure_plot_widget.export_as_image
        )
        self.top_ctrl.clear_plot_requested.connect(self._clear_pressure_plot)

        # ─── Window title and initial splitter sizing ───────────────────────────
        self.setWindowTitle(f"{APP_NAME} - v{APP_VERSION}")
        QTimer.singleShot(50, self._set_initial_splitter_sizes)

        self._set_initial_control_states()
        log.info("MainWindow initialized.")
        self.showMaximized()

    def _init_paths_and_icons(self):
        base = os.path.dirname(os.path.abspath(__file__))
        icon_dir = os.path.join(base, "ui", "icons")
        if not os.path.isdir(icon_dir):
            # Attempt to find icons if script is run from within prim_app directory
            alt_icon_dir = os.path.join(
                os.path.dirname(base), "prim_app", "ui", "icons"
            )
            if os.path.isdir(alt_icon_dir):
                icon_dir = alt_icon_dir
            else:  # Try one level up from base for cases like running tests from project root
                another_alt_icon_dir = os.path.join(
                    os.path.dirname(base), "ui", "icons"
                )
                if os.path.isdir(another_alt_icon_dir):
                    icon_dir = another_alt_icon_dir
                else:
                    log.warning(
                        f"Icon directory not found. Looked in: {icon_dir}, {alt_icon_dir}, {another_alt_icon_dir}"
                    )

        def get_icon(name):
            path = os.path.join(icon_dir, name)
            return QIcon(path) if os.path.exists(path) else QIcon()

        self.icon_record_start = get_icon("record.svg")
        self.icon_record_stop = get_icon("stop.svg")
        self.icon_recording_active = get_icon("recording_active.svg")
        self.icon_connect = get_icon("plug.svg")
        self.icon_disconnect = get_icon("plug_disconnect.svg")

    def _build_console_log_dock(self):
        self.dock_console = QDockWidget("Console Log", self)
        self.dock_console.setObjectName("ConsoleLogDock")
        self.dock_console.setAllowedAreas(
            Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea
        )
        console_widget = QWidget()
        layout = QVBoxLayout(console_widget)
        self.console_out_textedit = QTextEdit(readOnly=True)
        self.console_out_textedit.setFontFamily("monospace")
        layout.addWidget(self.console_out_textedit)
        self.dock_console.setWidget(console_widget)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.dock_console)
        self.dock_console.setVisible(False)

    def _build_central_widget_layout(self):
        """
        Builds a layout that matches:
        ┌────────────────────────────────────────────────────────────────┐
        │  Top Row:  [Camera Controls Tabs] [Device Status Panel] [Plot Controls Panel] │
        ├────────────────────────────────────────────────────────────────┤
        │  Bottom Row:  [QtCameraWidget (live feed)] | [PressurePlotWidget (plot)]   │
        └────────────────────────────────────────────────────────────────┘
        """

        # ----------------------------
        # 1) Create the container
        # ----------------------------
        central = QWidget()
        main_vlay = QVBoxLayout(central)
        main_vlay.setContentsMargins(4, 4, 4, 4)
        main_vlay.setSpacing(6)

        # ----------------------------
        # 2) Build the Top Row
        # ----------------------------
        top_row_widget = QWidget()
        top_row_lay = QHBoxLayout(top_row_widget)
        top_row_lay.setContentsMargins(0, 0, 0, 0)
        top_row_lay.setSpacing(10)

        # -- 2a) Camera Controls (TabWidget with three tabs) --
        camera_tabs = QTabWidget()
        camera_tabs.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

        # --- Tab 1: Source (Device & Resolution selection + “Start Camera” button) ---
        source_tab = QWidget()
        source_lay = QFormLayout(source_tab)
        source_lay.setContentsMargins(6, 6, 6, 6)
        source_lay.setSpacing(6)

        # Device dropdown (will be populated at runtime)
        self.device_combo = QComboBox()
        self.device_combo.addItem("Select Device...", None)  # Placeholder
        source_lay.addRow("Device:", self.device_combo)

        # Resolution dropdown (populated after device enumeration)
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItem("Select Resolution...", None)
        source_lay.addRow("Resolution:", self.resolution_combo)

        # Start/Stop Camera button
        self.btn_start_camera = QPushButton("Start Camera")
        self.btn_start_camera.clicked.connect(self._on_start_stop_camera)
        source_lay.addRow("", self.btn_start_camera)

        camera_tabs.addTab(source_tab, "Source")

        # --- Tab 2: Adjustments (Gain, Brightness, Auto-Exposure, etc.) ---
        adjustments_tab = QWidget()
        adjustments_lay = QVBoxLayout(adjustments_tab)
        adjustments_lay.setContentsMargins(6, 6, 6, 6)
        adjustments_lay.setSpacing(6)

        # Our dynamic CameraControlPanel (builds sliders for Gain, Brightness, etc.)
        # We’ll instantiate it with a placeholder – it will be enabled once the camera thread is ready.
        self.camera_control_panel = CameraControlPanel(
            camera_thread=self.camera_widget._cam_thread, parent=self
        )
        self.camera_control_panel.setEnabled(False)  # Disabled until camera is running
        adjustments_lay.addWidget(self.camera_control_panel)

        camera_tabs.addTab(adjustments_tab, "Adjustments")

        # --- Tab 3: Region of Interest (ROI) (Placeholder) ---
        roi_tab = QWidget()
        roi_lay = QVBoxLayout(roi_tab)
        roi_lay.setContentsMargins(6, 6, 6, 6)
        roi_lay.setSpacing(6)

        # Placeholder text – you can replace with actual ROI controls later
        roi_placeholder = QLabel("ROI controls will go here.")
        roi_placeholder.setAlignment(Qt.AlignCenter)
        roi_lay.addWidget(roi_placeholder)

        camera_tabs.addTab(roi_tab, "Region of Interest (ROI)")

        # Add the camera_tabs to the top-left of the top row
        top_row_lay.addWidget(camera_tabs, stretch=2)

        # -- 2b) Device Status Panel (Centered) --
        status_panel = QGroupBox("PRIM Device Status")
        status_lay = QFormLayout(status_panel)
        status_lay.setContentsMargins(6, 6, 6, 6)
        status_lay.setSpacing(4)

        # Connection status label
        self.lbl_connection = QLabel("Disconnected")
        status_lay.addRow("Connection:", self.lbl_connection)

        # Device Frame # label
        self.lbl_frame_number = QLabel("0")
        status_lay.addRow("Device Frame #:", self.lbl_frame_number)

        # Device Time (s) label
        self.lbl_device_time = QLabel("0.00")
        status_lay.addRow("Device Time (s):", self.lbl_device_time)

        # Current Pressure (mmHg) label
        self.lbl_current_pressure = QLabel("0.00")
        status_lay.addRow("Current Pressure:", self.lbl_current_pressure)

        # Make status panel a fixed‐width so it doesn’t expand too wide
        status_panel.setFixedWidth(250)
        top_row_lay.addWidget(status_panel, stretch=1)

        # -- 2c) Plot Controls Panel (Right) --
        plot_ctrl_panel = QGroupBox("Plot Controls")
        plot_lay = QFormLayout(plot_ctrl_panel)
        plot_lay.setContentsMargins(6, 6, 6, 6)
        plot_lay.setSpacing(4)

        # Auto-scale X checkbox
        self.chk_autoscale_x = QCheckBox("Auto‐scale X")
        self.chk_autoscale_x.setChecked(True)
        self.chk_autoscale_x.stateChanged.connect(self._on_autoscale_x_toggled)
        plot_lay.addRow("", self.chk_autoscale_x)

        # X‐Limits Min / Max
        self.edit_xmin = QLineEdit("0.0")
        self.edit_xmin.setEnabled(False)
        self.edit_xmax = QLineEdit("0.0")
        self.edit_xmax.setEnabled(False)
        xlimits_row = QWidget()
        xlimits_lay = QHBoxLayout(xlimits_row)
        xlimits_lay.setContentsMargins(0, 0, 0, 0)
        xlimits_lay.setSpacing(4)
        xlimits_lay.addWidget(QLabel("Min:"))
        xlimits_lay.addWidget(self.edit_xmin)
        xlimits_lay.addWidget(QLabel("Max:"))
        xlimits_lay.addWidget(self.edit_xmax)
        plot_lay.addRow("X‐Limits:", xlimits_row)

        # Auto‐scale Y checkbox
        self.chk_autoscale_y = QCheckBox("Auto‐scale Y")
        self.chk_autoscale_y.setChecked(True)
        self.chk_autoscale_y.stateChanged.connect(self._on_autoscale_y_toggled)
        plot_lay.addRow("", self.chk_autoscale_y)

        # Y‐Limits Min / Max
        self.edit_ymin = QLineEdit("0.0")
        self.edit_ymin.setEnabled(False)
        self.edit_ymax = QLineEdit("30.0")
        self.edit_ymax.setEnabled(False)
        ylimits_row = QWidget()
        ylimits_lay = QHBoxLayout(ylimits_row)
        ylimits_lay.setContentsMargins(0, 0, 0, 0)
        ylimits_lay.setSpacing(4)
        ylimits_lay.addWidget(QLabel("Min:"))
        ylimits_lay.addWidget(self.edit_ymin)
        ylimits_lay.addWidget(QLabel("Max:"))
        ylimits_lay.addWidget(self.edit_ymax)
        plot_lay.addRow("Y‐Limits:", ylimits_row)

        # Reset Zoom/View button
        btn_reset_zoom = QPushButton("Reset Zoom/View")
        btn_reset_zoom.clicked.connect(self._on_reset_zoom)
        plot_lay.addRow("", btn_reset_zoom)

        # Export Plot Image button
        btn_export_plot = QPushButton("Export Plot Image")
        btn_export_plot.clicked.connect(self._on_export_plot_image)
        plot_lay.addRow("", btn_export_plot)

        # Fix its width so it doesn’t expand too large
        plot_ctrl_panel.setFixedWidth(300)
        top_row_lay.addWidget(plot_ctrl_panel, stretch=1)

        # Add the completed top row to the main vertical layout
        main_vlay.addWidget(top_row_widget, stretch=0)

        # ----------------------------
        # 3) Build the Bottom Row (Camera View | Plot)
        # ----------------------------
        self.bottom_split = QSplitter(Qt.Horizontal)
        self.bottom_split.setChildrenCollapsible(False)

        # -- 3a) Left: Live Camera Feed --
        self.camera_widget = QtCameraWidget(self)
        self.camera_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.bottom_split.addWidget(self.camera_widget)

        # -- 3b) Right: Pressure Plot --
        self.pressure_plot_widget = PressurePlotWidget(self)
        self.pressure_plot_widget.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self.bottom_split.addWidget(self.pressure_plot_widget)

        # Balance the two panes roughly equally
        self.bottom_split.setStretchFactor(0, 1)
        self.bottom_split.setStretchFactor(1, 1)

        main_vlay.addWidget(self.bottom_split, stretch=1)

        # Finally, set this as the central widget
        self.setCentralWidget(central)

    def _build_menus(self):
        mb = self.menuBar()
        fm = mb.addMenu("&File")
        exp_data_act = QAction(
            "Export Plot &Data (CSV)â¦", self, triggered=self._export_plot_data_as_csv
        )
        fm.addAction(exp_data_act)
        exp_img_act = QAction("Export Plot &Imageâ¦", self)
        if hasattr(self, "pressure_plot_widget") and self.pressure_plot_widget:
            exp_img_act.triggered.connect(self.pressure_plot_widget.export_as_image)
        fm.addAction(exp_img_act)
        fm.addSeparator()
        exit_act = QAction(
            "&Exit", self, shortcut=QKeySequence.Quit, triggered=self.close
        )
        fm.addAction(exit_act)

        am = mb.addMenu("&Acquisition")
        self.start_recording_action = QAction(
            self.icon_record_start,
            "Start &Recording",
            self,
            shortcut=Qt.CTRL | Qt.Key_R,
            triggered=self._trigger_start_recording_dialog,
            enabled=False,
        )
        am.addAction(self.start_recording_action)
        self.stop_recording_action = QAction(
            self.icon_record_stop,
            "Stop R&ecording",
            self,
            shortcut=Qt.CTRL | Qt.Key_T,
            triggered=self._trigger_stop_recording,
            enabled=False,
        )
        am.addAction(self.stop_recording_action)

        vm = mb.addMenu("&View")
        if hasattr(self, "dock_console") and self.dock_console:
            vm.addAction(self.dock_console.toggleViewAction())

        pm = mb.addMenu("&Plot")
        clear_plot_act = QAction(
            "&Clear Plot Data", self, triggered=self._clear_pressure_plot
        )
        pm.addAction(clear_plot_act)

        def trigger_reset_zoom():
            if (
                hasattr(self, "pressure_plot_widget")
                and self.pressure_plot_widget
                and hasattr(self, "top_ctrl")
                and self.top_ctrl
                and hasattr(self.top_ctrl, "plot_controls")
                and self.top_ctrl.plot_controls
            ):
                self.pressure_plot_widget.reset_zoom(
                    self.top_ctrl.plot_controls.auto_x_cb.isChecked(),
                    self.top_ctrl.plot_controls.auto_y_cb.isChecked(),
                )
            else:
                log.warning("Cannot reset zoom, UI components missing.")

        reset_zoom_act = QAction("&Reset Plot Zoom", self, triggered=trigger_reset_zoom)
        pm.addAction(reset_zoom_act)

        hm = mb.addMenu("&Help")
        about_act = QAction(
            f"&About {APP_NAME}", self, triggered=self._show_about_dialog
        )
        hm.addAction(about_act)
        hm.addAction("About &Qt", QApplication.instance().aboutQt)

    def _build_main_toolbar(self):
        tb = QToolBar("Main Controls")
        tb.setObjectName("MainControlsToolbar")
        tb.setIconSize(QSize(20, 20))
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(Qt.TopToolBarArea, tb)
        self.connect_serial_action = QAction(
            self.icon_connect,
            "&Connect PRIM Device",
            self,
            triggered=self._toggle_serial_connection,
        )
        tb.addAction(self.connect_serial_action)
        self.serial_port_combobox = QComboBox()
        self.serial_port_combobox.setToolTip("Select Serial Port")
        self.serial_port_combobox.setMinimumWidth(200)
        self.serial_port_combobox.addItem(
            "ð Simulated Data", QVariant()
        )  # Ensure QVariant for None/empty
        ports = list_serial_ports()
        if ports:
            for p_dev, p_desc in ports:
                self.serial_port_combobox.addItem(
                    f"{os.path.basename(p_dev)} ({p_desc})", QVariant(p_dev)
                )
        else:
            self.serial_port_combobox.addItem(
                "No Serial Ports Found", QVariant()
            )  # QVariant for None
            self.serial_port_combobox.setEnabled(False)
        tb.addWidget(self.serial_port_combobox)
        tb.addSeparator()
        if hasattr(self, "start_recording_action"):
            tb.addAction(self.start_recording_action)
        if hasattr(self, "stop_recording_action"):
            tb.addAction(self.stop_recording_action)

    def _build_status_bar(self):
        sb = self.statusBar()
        # self.setStatusBar(sb) # Not needed, statusBar() returns the existing one or creates it
        self.app_session_time_label = QLabel("Session: 00:00:00")
        sb.addPermanentWidget(self.app_session_time_label)
        self._app_session_seconds = 0
        self._app_session_timer = QTimer(self)
        self._app_session_timer.setInterval(1000)
        self._app_session_timer.timeout.connect(self._update_app_session_time)
        self._app_session_timer.start()

    @pyqtSlot()
    def _clear_pressure_plot(self):
        if self.pressure_plot_widget:
            self.pressure_plot_widget.clear_plot()
            self.statusBar().showMessage("Pressure plot data cleared.", 3000)

    def _set_initial_splitter_sizes(self):
        if self.bottom_split:
            w = self.bottom_split.width()
            if w > 0:  # Ensure width is positive before calculating
                self.bottom_split.setSizes([int(w * 0.6), int(w * 0.4)])
            else:  # Fallback or retry if width is not yet available
                QTimer.singleShot(100, self._set_initial_splitter_sizes)

    def _set_initial_control_states(self):
        if self.top_ctrl:
            self.top_ctrl.update_connection_status("Disconnected", False)
        if hasattr(self, "start_recording_action"):
            self.start_recording_action.setEnabled(False)
        if hasattr(self, "stop_recording_action"):
            self.stop_recording_action.setEnabled(False)
        if self.camera_widget:
            self.camera_widget.setEnabled(False)  # Disable camera widget until needed

    @pyqtSlot(str)
    def _handle_serial_status_change(self, status: str):
        log.info(f"Serial status: {status}")
        self.statusBar().showMessage(f"PRIM Device: {status}", 4000)
        # Determine connected state more reliably
        connected = (
            "connected" in status.lower()
            or "opened serial port" in status.lower()
            or "simulation mode" in status.lower()
        )  # Simulation is also a "connected" state for UI

        if self.top_ctrl:
            self.top_ctrl.update_connection_status(status, connected)

        self.connect_serial_action.setIcon(
            self.icon_disconnect if connected else self.icon_connect
        )
        self.connect_serial_action.setText(
            f"{'Disconnect' if connected else 'Connect'} PRIM Device"
        )
        self.serial_port_combobox.setEnabled(not connected)

        if connected and self.pressure_plot_widget:
            self.pressure_plot_widget.clear_plot()  # Clear plot on new connection
            # Update placeholder if switching to simulation or real device
            if "simulation mode" in status.lower():
                self.pressure_plot_widget._update_placeholder(
                    "Waiting for PRIM device data (Simulation)..."
                )
            else:
                self.pressure_plot_widget._update_placeholder(
                    "Waiting for PRIM device data..."
                )

        if not connected and self._is_recording:
            # This implies a disconnection during recording
            QMessageBox.warning(
                self,
                "Recording Auto-Stopped",
                "PRIM device disconnected. Recording stopped.",
            )
            self._trigger_stop_recording()  # Stop recording if device disconnects

        self._update_recording_actions_enable_state()

    @pyqtSlot(str)
    def _handle_serial_error(self, msg: str):
        log.error(f"Serial error: {msg}")
        self.statusBar().showMessage(f"Serial Error: {msg}", 6000)
        # If the error implies disconnection, update status accordingly
        if (
            "disconnecting" in msg.lower()
            or "error opening" in msg.lower()
            or "serial error" in msg.lower()
        ):
            self._handle_serial_status_change(f"Error: {msg}. Disconnected.")
        self._update_recording_actions_enable_state()  # Re-evaluate recording actions

    @pyqtSlot()
    def _handle_serial_thread_finished(self):
        log.info("SerialThread 'finished' signal received.")
        sender = self.sender()

        # Check if the sender is the current _serial_thread instance
        if self._serial_thread is sender:
            current_conn_text = ""
            if self.top_ctrl and hasattr(self.top_ctrl, "conn_lbl"):
                # Check current displayed status to avoid redundant "Disconnected" messages
                # if the status was already set to an error or disconnected state.
                current_conn_text = self.top_ctrl.conn_lbl.text().lower()

            # Only update status if it wasn't already set to an error/disconnected state by _handle_serial_error or explicit stop
            if not (
                "error" in current_conn_text
                or "failed" in current_conn_text
                or "disconnected" in current_conn_text
            ):
                if (
                    "simulation" not in current_conn_text
                ):  # Don't show "Disconnected" if it was just simulation ending.
                    self._handle_serial_status_change("Disconnected")

            if self._serial_thread:  # Double check before deleteLater
                self._serial_thread.deleteLater()
            self._serial_thread = None
            log.info("Current _serial_thread instance cleaned up.")
        elif sender and isinstance(
            sender, SerialThread
        ):  # Check if it's an orphaned SerialThread
            log.warning(
                "Received 'finished' from an orphaned SerialThread instance. Cleaning it up."
            )
            sender.deleteLater()
        else:  # Should not happen
            log.warning(
                "Received 'finished' signal, but sender is not the expected SerialThread or is None."
            )

        self._update_recording_actions_enable_state()

    @pyqtSlot(int, float, float)
    def _handle_new_serial_data(self, idx: int, t: float, p: float):
        plot_ctrls = getattr(self.top_ctrl, "plot_controls", None)
        if plot_ctrls:  # Ensure plot_ctrls exists
            self.top_ctrl.update_prim_data(
                idx, t, p
            )  # Update labels in TopControlPanel
            if self.pressure_plot_widget:
                self.pressure_plot_widget.update_plot(
                    t,
                    p,
                    plot_ctrls.auto_x_cb.isChecked(),
                    plot_ctrls.auto_y_cb.isChecked(),
                )

        # Optional: Console logging for new data (can be verbose)
        # if self.dock_console and self.dock_console.isVisible() and self.console_out_textedit:
        #     self.console_out_textedit.append(f"PRIM Data: Idx={idx}, Time={t:.3f}s, P={p:.2f}")

        if self._is_recording and self._recording_worker:
            try:
                self._recording_worker.add_csv_data(t, idx, p)
            except Exception as e_csv:
                log.exception(f"Error adding CSV data to recording queue: {e_csv}")
                self.statusBar().showMessage(
                    "CRITICAL: Error queueing CSV data. Recording data may be lost.",
                    5000,
                )
                # Potentially stop recording or flag major error
                # self._trigger_stop_recording()

    def _toggle_serial_connection(self):
        if self._serial_thread and self._serial_thread.isRunning():
            log.info("User requested to stop serial connection.")
            self._serial_thread.stop()  # stop() in SerialThread should set self.running = False
            # The finished signal from SerialThread will handle cleanup.
        else:
            # Get selected port from combobox
            selected_index = self.serial_port_combobox.currentIndex()
            port_to_use_variant = self.serial_port_combobox.itemData(selected_index)
            port_to_use = (
                port_to_use_variant if isinstance(port_to_use_variant, str) else None
            )  # Ensure it's a string or None

            current_text = self.serial_port_combobox.currentText()
            is_simulation = "simulated data" in current_text.lower()

            if not port_to_use and not is_simulation:
                QMessageBox.warning(
                    self,
                    "Serial Connection Error",
                    "Please select a valid serial port or choose 'Simulated Data'.",
                )
                return

            log.info(
                f"User requested to start serial connection: Port='{port_to_use if port_to_use else 'Simulation'}'"
            )

            # Cleanup old thread instance if it exists (e.g., from a previous failed start)
            if self._serial_thread:
                log.debug(
                    "Cleaning up previous _serial_thread instance before starting new one."
                )
                if (
                    self._serial_thread.isRunning()
                ):  # Should not happen if logic is correct, but as a safeguard
                    self._serial_thread.stop()
                    self._serial_thread.wait(500)  # Brief wait
                self._serial_thread.deleteLater()
                self._serial_thread = None
                QApplication.processEvents()

            try:
                self._serial_thread = SerialThread(
                    port=port_to_use, parent=self
                )  # Pass parent for auto-cleanup
                # Connect signals
                self._serial_thread.data_ready.connect(self._handle_new_serial_data)
                self._serial_thread.error_occurred.connect(self._handle_serial_error)
                self._serial_thread.status_changed.connect(
                    self._handle_serial_status_change
                )
                self._serial_thread.finished.connect(
                    self._handle_serial_thread_finished
                )

                self._serial_thread.start()  # Start the thread
            except Exception as e:
                log.exception("Failed to create or start SerialThread.")
                QMessageBox.critical(
                    self,
                    "Serial Thread Error",
                    f"Could not start serial communication: {e}",
                )
                if (
                    self._serial_thread
                ):  # If instance was created but start failed or other error
                    self._serial_thread.deleteLater()
                    self._serial_thread = None
                self._update_recording_actions_enable_state()  # Ensure UI reflects failure

    def _update_recording_actions_enable_state(self):
        # Recording can start if serial is ready (connected or simulating) AND not already recording
        serial_ready_for_recording = (
            self._serial_thread is not None
            and self._serial_thread.isRunning()
            and (
                "connected" in self.top_ctrl.conn_lbl.text().lower()
                or "simulation mode" in self.top_ctrl.conn_lbl.text().lower()
                or "opened serial port" in self.top_ctrl.conn_lbl.text().lower()
            )
        )

        can_start_recording = serial_ready_for_recording and not self._is_recording
        can_stop_recording = self._is_recording  # Can only stop if currently recording

        if hasattr(self, "start_recording_action"):
            self.start_recording_action.setEnabled(can_start_recording)
        if hasattr(self, "stop_recording_action"):
            self.stop_recording_action.setEnabled(can_stop_recording)

    def _trigger_start_recording_dialog(self):
        # Check if serial connection is active (real or simulated)
        serial_is_active = (
            self._serial_thread
            and self._serial_thread.isRunning()
            and (
                "connected" in self.top_ctrl.conn_lbl.text().lower()
                or "simulation mode" in self.top_ctrl.conn_lbl.text().lower()
                or "opened serial port" in self.top_ctrl.conn_lbl.text().lower()
            )
        )

        if not serial_is_active:
            QMessageBox.warning(
                self,
                "Cannot Start Recording",
                "PRIM device (or simulation) is not active.",
            )
            return
        if self._is_recording:
            QMessageBox.information(
                self,
                "Recording Already Active",
                "A recording session is already in progress.",
            )
            return

        # --- Recording Dialog ---
        dialog = QDialog(self)
        dialog.setWindowTitle("New Recording Session Details")
        layout = QFormLayout(dialog)

        # Session Name
        default_session_name = (
            f"Session_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}"
        )
        name_edit = QLineEdit(default_session_name)
        name_edit.setPlaceholderText("Enter a unique session name")
        layout.addRow("Session Name:", name_edit)

        # Operator
        operator_edit = QLineEdit(
            load_app_setting("last_operator", "")
        )  # Load last used operator
        operator_edit.setPlaceholderText("Operator's name/initials")
        layout.addRow("Operator:", operator_edit)

        # Notes
        notes_edit = QTextEdit()
        notes_edit.setPlaceholderText("Optional notes about the session...")
        notes_edit.setFixedHeight(80)  # Reasonable default height
        layout.addRow("Notes:", notes_edit)

        # Dialog Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec_() != QDialog.Accepted:
            log.info("Recording dialog cancelled by user.")
            return

        # --- Process Dialog Input ---
        save_app_setting(
            "last_operator", operator_edit.text()
        )  # Save operator for next time

        session_name_raw = name_edit.text().strip()
        if not session_name_raw:  # Use placeholder if empty
            session_name_raw = (
                name_edit.placeholderText()
                if name_edit.placeholderText()
                else default_session_name
            )

        # Sanitize session name for folder/file usage
        session_name_safe = "".join(
            c if c.isalnum() or c in ("_", "-") else "_" for c in session_name_raw
        )
        session_name_safe = re.sub(r"_+", "_", session_name_safe).strip(
            "_"
        )  # Replace multiple underscores and strip leading/trailing
        if not session_name_safe:  # Fallback if sanitization results in empty string
            session_name_safe = f"Session_Unnamed_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}"

        # --- Create Session Folder and Define Paths ---
        session_folder = os.path.join(PRIM_RESULTS_DIR, session_name_safe)
        try:
            os.makedirs(session_folder, exist_ok=True)
            log.info(f"Session folder created/ensured: {session_folder}")
        except OSError as e_mkdir:
            log.error(f"Failed to create session folder '{session_folder}': {e_mkdir}")
            QMessageBox.critical(
                self,
                "File System Error",
                f"Could not create session folder:\n{e_mkdir}",
            )
            return

        # Base path for recording files (video, CSV) without extension
        recording_base_prefix = os.path.join(session_folder, session_name_safe)
        self.last_trial_basepath = session_folder  # Store parent folder for later access (e.g., saving plot data)

        # --- Determine Recording Parameters (FPS, Frame Size) ---
        # For simplified camera, we might not have reliable dynamic frame size/fps from camera settings yet.
        # Using defaults from config.py, but ideally, this would come from an active (even if simplified) camera stream.
        # For now, assume we don't have live camera parameters for recording.
        # This part will need adjustment once simplified camera feed is stable and provides frame info.

        w, h = DEFAULT_FRAME_SIZE  # Fallback
        record_fps = DEFAULT_FPS  # Fallback

        log.warning(
            "Using default frame size and FPS for recording as simplified camera does not yet provide this. Video may not match live view if camera defaults differ."
        )
        # TODO: Once basic live feed is working, get frame dimensions from the received frames for the recorder.
        # Example: if self.camera_view and self.camera_view.current_frame_width > 0:
        # w, h = self.camera_view.current_frame_width, self.camera_view.current_frame_height
        # record_fps = self.camera_thread.target_fps # Or a fixed value if target_fps isn't reliable yet

        video_ext = DEFAULT_VIDEO_EXTENSION.lower()
        codec = DEFAULT_VIDEO_CODEC
        log.info(
            f"Preparing to start recording: Session='{session_name_safe}'. Target Params: FPS={record_fps}, Size={w}x{h}, Format={video_ext}/{codec}"
        )

        # --- Start Recording Worker ---
        try:
            # Ensure any previous worker is stopped and cleaned up
            if self._recording_worker and self._recording_worker.isRunning():
                log.info("Stopping previous recording worker before starting new one.")
                self._recording_worker.stop_worker()
                if not self._recording_worker.wait(2000):  # Wait for graceful stop
                    log.warning(
                        "Previous recording worker did not stop gracefully, terminating."
                    )
                    self._recording_worker.terminate()
                    self._recording_worker.wait(500)
            if self._recording_worker:
                self._recording_worker.deleteLater()
                self._recording_worker = None
                QApplication.processEvents()

            self._recording_worker = RecordingWorker(
                basepath=recording_base_prefix,
                fps=record_fps,
                frame_size=(w, h),
                video_ext=video_ext,
                video_codec=codec,
                parent=self,  # For Qt parent-child cleanup
            )
            self._recording_worker.start()

            # Wait a bit for the worker to initialize its internal TrialRecorder
            # A more robust way would be a signal from RecordingWorker once it's truly ready.
            QThread.msleep(700)  # Increased sleep for robustness

            if not (
                self._recording_worker
                and self._recording_worker.isRunning()
                and self._recording_worker.is_ready_to_record  # Crucial check
            ):
                log.error(
                    "RecordingWorker started but did not report as ready (is_ready_to_record is false)."
                )
                # Attempt to get more detailed error if TrialRecorder init failed (this is complex)
                # For now, a generic error.
                raise RuntimeError(
                    "Recording worker or its internal TrialRecorder failed readiness check. Check logs for TrialRecorder errors."
                )

            self._is_recording = True
            if hasattr(self, "start_recording_action"):
                self.start_recording_action.setIcon(
                    self.icon_recording_active
                )  # Update icon
            self._update_recording_actions_enable_state()  # Update button states

            if self.pressure_plot_widget:
                self.pressure_plot_widget.clear_plot()  # Clear plot for new recording session

            self.statusBar().showMessage(
                f"ð´ REC: {session_name_safe}", 0  # Persistent message (0 timeout)
            )
            log.info(f"Recording started successfully for session: {session_name_safe}")

        except Exception as e_rec_start:
            log.exception(
                f"Critical error during recording start sequence: {e_rec_start}"
            )
            QMessageBox.critical(
                self,
                "Recording Start Error",
                f"Could not start recording worker:\n{e_rec_start}",
            )
            if self._recording_worker:  # Cleanup if worker was created but failed
                if self._recording_worker.isRunning():
                    self._recording_worker.stop_worker()
                    self._recording_worker.wait(500)
                self._recording_worker.deleteLater()
                self._recording_worker = None
            self._is_recording = False
            self._update_recording_actions_enable_state()  # Reset UI
            if self.statusBar().currentMessage().startswith("ð´ REC:"):
                self.statusBar().clearMessage()
            return

    def _trigger_stop_recording(self):
        if not self._is_recording or not self._recording_worker:
            log.info(
                "Stop recording called, but not currently recording or worker is missing."
            )
            if self._is_recording:  # If flag is somehow true without worker, reset it
                self._is_recording = False
            self._update_recording_actions_enable_state()
            if self.statusBar().currentMessage().startswith("ð´ REC:"):
                self.statusBar().clearMessage()
            return

        log.info("User requested to stop recording...")
        # Determine session name for messages (safer access)
        session_name_stopped = "Session"  # Default
        if hasattr(self, "last_trial_basepath") and self.last_trial_basepath:
            # Extract from the folder name, which should be the sanitized session name
            base_folder_name = os.path.basename(self.last_trial_basepath)
            if base_folder_name:  # Ensure it's not empty
                session_name_stopped = base_folder_name

        try:
            # Signal the worker to stop and wait for it to finish processing its queue
            self._recording_worker.stop_worker()  # This queues a 'stop' sentinel
            log.debug(
                "Waiting for RecordingWorker to finish processing queue and stop..."
            )
            if not self._recording_worker.wait(
                10000
            ):  # Increased timeout for potentially large queues
                log.warning(
                    "RecordingWorker did not stop gracefully within timeout, terminating."
                )
                self._recording_worker.terminate()  # Force terminate if unresponsive
                self._recording_worker.wait(1000)  # Wait for termination to complete
            log.info("RecordingWorker thread has finished or been terminated.")

            # Get final frame count (safer access)
            count = 0
            if hasattr(
                self._recording_worker, "video_frame_count"
            ):  # Check if property exists
                count = self._recording_worker.video_frame_count

            self.statusBar().showMessage(
                f"Recording '{session_name_stopped}' stopped. {count} video frames recorded.",
                7000,
            )

            # Auto-save plot data for the session that just ended
            if hasattr(self, "last_trial_basepath") and self.last_trial_basepath:
                self._save_current_plot_data_for_session()  # Save plot data

                # Ask user if they want to open the folder
                if (
                    QMessageBox.information(
                        self,
                        "Recording Saved",
                        f"Session '{session_name_stopped}' data saved to:\n{self.last_trial_basepath}\n\nVideo frames recorded: {count}\n\nOpen session folder?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No,  # Default to No
                    )
                    == QMessageBox.Yes
                ):
                    try:
                        if sys.platform == "win32":
                            os.startfile(self.last_trial_basepath)
                        elif sys.platform == "darwin":  # macOS
                            os.system(f'open "{self.last_trial_basepath}"')
                        else:  # Linux and other POSIX
                            os.system(f'xdg-open "{self.last_trial_basepath}"')
                    except Exception as e_open:
                        log.error(
                            f"Error opening session folder '{self.last_trial_basepath}': {e_open}"
                        )
                        QMessageBox.warning(
                            self,
                            "Open Folder Error",
                            f"Could not open folder:\n{e_open}",
                        )
            else:
                QMessageBox.information(
                    self,
                    "Recording Stopped",
                    f"{count} video frames recorded. Path information was missing for auto-save features.",
                )

        except Exception as e_stop_rec:
            log.exception(
                f"Error during user-initiated stop recording sequence: {e_stop_rec}"
            )
            self.statusBar().showMessage(
                f"Error stopping recording: {e_stop_rec}", 5000
            )
        finally:
            # Cleanup worker instance
            if self._recording_worker:
                self._recording_worker.deleteLater()  # Schedule for deletion
            self._recording_worker = None
            self._is_recording = False  # Crucial: reset recording flag

            if hasattr(self, "start_recording_action"):
                self.start_recording_action.setIcon(
                    self.icon_record_start
                )  # Reset icon

            self._update_recording_actions_enable_state()  # Update UI button states

            if self.statusBar().currentMessage().startswith("ð´ REC:"):
                self.statusBar().clearMessage()  # Clear persistent recording message
            log.info("Recording fully stopped and UI updated.")

    def _save_current_plot_data_for_session(self):
        if not hasattr(self, "last_trial_basepath") or not self.last_trial_basepath:
            log.warning("Cannot auto-save plot data: 'last_trial_basepath' is not set.")
            return
        if not (
            self.pressure_plot_widget
            and self.pressure_plot_widget.times
            and self.pressure_plot_widget.pressures
        ):
            log.info("No plot data available to auto-save for the session.")
            return

        # Determine session name from the folder path for the CSV filename
        session_name_for_file = os.path.basename(self.last_trial_basepath)
        if not session_name_for_file:  # Fallback if base path itself is odd
            session_name_for_file = "session_plot"

        csv_filename = f"{session_name_for_file}_pressure_plot_data.csv"
        csv_path = os.path.join(self.last_trial_basepath, csv_filename)

        try:
            with open(csv_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["time_s", "pressure_mmHg"])  # Header
                for t, p in zip(
                    self.pressure_plot_widget.times, self.pressure_plot_widget.pressures
                ):
                    writer.writerow(
                        [f"{t:.6f}", f"{p:.6f}"]
                    )  # Format to 6 decimal places
            log.info(f"Session plot data automatically saved to: {csv_path}")
            self.statusBar().showMessage(
                f"Plot CSV for session '{session_name_for_file}' saved.", 4000
            )
        except Exception as e_save_plot:
            log.exception(
                f"Failed to auto-save session plot data to '{csv_path}': {e_save_plot}"
            )
            QMessageBox.warning(
                self,
                "Plot Data Save Error",
                f"Could not automatically save plot CSV data:\n{e_save_plot}",
            )

    @pyqtSlot()
    def _export_plot_data_as_csv(self):
        if not (
            self.pressure_plot_widget
            and self.pressure_plot_widget.times
            and self.pressure_plot_widget.pressures
        ):
            QMessageBox.information(
                self, "No Data to Export", "The pressure plot has no data to export."
            )
            return

        default_filename = f"manual_plot_export_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Plot Data as CSV", default_filename, "CSV Files (*.csv)"
        )
        if not path:  # User cancelled
            return

        try:
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["time_s", "pressure_mmHg"])  # Header
                for t, p in zip(
                    self.pressure_plot_widget.times, self.pressure_plot_widget.pressures
                ):
                    writer.writerow([f"{t:.6f}", f"{p:.6f}"])
            self.statusBar().showMessage(
                f"Plot data successfully exported to {os.path.basename(path)}", 4000
            )
            log.info(f"Plot data manually exported to: {path}")
        except Exception as e_export:
            log.exception(
                f"Failed to manually export plot data to '{path}': {e_export}"
            )
            QMessageBox.critical(
                self, "Export Error", f"Could not save plot CSV data:\n{e_export}"
            )

    @pyqtSlot()
    def _show_about_dialog(self):
        QMessageBox.about(self, f"About {APP_NAME}", ABOUT_TEXT)

    def _update_app_session_time(self):
        self._app_session_seconds += 1
        h, rem = divmod(self._app_session_seconds, 3600)
        m, s = divmod(rem, 60)
        self.app_session_time_label.setText(f"Session: {h:02}:{m:02}:{s:02}")

    @pyqtSlot(str, str)
    def _on_camera_error(self, msg: str, code: str):
        """
        Called whenever SDKCameraThread.error emits (message, error_code).
        Shows a critical pop‐up, stops the thread, and updates the status bar.
        """
        log.error(f"Camera error occurred ({code}): {msg}")
        QMessageBox.critical(self, "Camera Error", msg)

        # Stop and clean up the internal camera thread if it’s still running
        if (
            self.camera_widget
            and hasattr(self.camera_widget, "_cam_thread")
            and self.camera_widget._cam_thread.isRunning()
        ):
            try:
                log.info("Stopping SDKCameraThread due to error...")
                self.camera_widget._cam_thread.stop()
            except Exception as e_stop_cam_err:
                log.error(
                    f"Error stopping SDKCameraThread after error: {e_stop_cam_err}"
                )

        # Disable the entire camera widget, so user knows the feed isn’t active
        if self.camera_widget:
            self.camera_widget.setEnabled(False)

        # Update status bar
        self.statusBar().showMessage(
            "Camera Error! Live feed stopped or failed to start.", 0
        )

        # If a recording was in progress, stop it
        if self._is_recording and self._recording_worker:
            log.warning(
                "Camera error occurred during active recording. Stopping recording."
            )
            self._trigger_stop_recording()

    def closeEvent(self, event):
        log.info("MainWindow closeEvent triggered.")

        # If a recording is active, confirm before closing
        if self._is_recording:
            reply = QMessageBox.question(
                self,
                "Confirm Exit While Recording",
                "A recording session is currently active. Are you sure you want to stop recording and exit?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                log.info("User chose to stop recording and exit.")
                self._trigger_stop_recording()
                if self._recording_worker and hasattr(self._recording_worker, "wait"):
                    if not self._recording_worker.wait(5000):
                        log.warning(
                            "Recording worker did not finish cleanly. Forcing cleanup."
                        )
            else:
                log.info("User cancelled exit due to active recording.")
                event.ignore()
                return

        # Gracefully stop camera (if running) and other threads
        threads_to_clean = []

        # 1) CameraThread is now inside camera_widget
        if self.camera_widget and hasattr(self.camera_widget, "_cam_thread"):
            cam_thread = self.camera_widget._cam_thread
            threads_to_clean.append(
                ("SDKCameraThread", cam_thread, getattr(cam_thread, "stop", None))
            )

        # 2) SerialThread (unchanged)
        threads_to_clean.append(
            (
                "SerialThread",
                self._serial_thread,
                getattr(self._serial_thread, "stop", None),
            )
        )

        # 3) RecordingWorker (unchanged)
        threads_to_clean.append(
            (
                "RecordingWorker",
                self._recording_worker,
                getattr(self._recording_worker, "stop_worker", None),
            )
        )

        for name, thread_instance, stop_method in threads_to_clean:
            if thread_instance:
                if (
                    hasattr(thread_instance, "isRunning")
                    and thread_instance.isRunning()
                ):
                    log.info(
                        f"Stopping {name} ({thread_instance.__class__.__name__})..."
                    )
                    try:
                        if stop_method:
                            stop_method()
                        else:
                            log.warning(
                                f"No stop method for {name}, attempting terminate."
                            )

                        timeout = 3000 if name == "RecordingWorker" else 1500
                        if hasattr(
                            thread_instance, "wait"
                        ) and not thread_instance.wait(timeout):
                            log.warning(
                                f"{name} did not stop gracefully, forcing terminate."
                            )
                            if hasattr(thread_instance, "terminate"):
                                thread_instance.terminate()
                                thread_instance.wait(500)
                    except Exception as e:
                        log.error(f"Exception while stopping {name}: {e}")

                if hasattr(thread_instance, "deleteLater"):
                    thread_instance.deleteLater()

                # Nullify
                if name == "SDKCameraThread":
                    # The thread is owned by the widget; just set the widget disabled
                    self.camera_widget.setEnabled(False)
                elif name == "SerialThread":
                    self._serial_thread = None
                elif name == "RecordingWorker":
                    self._recording_worker = None
            else:
                log.debug(f"{name} was already None.")

        QApplication.processEvents()
        log.info("All threads cleaned up. Proceeding with close.")
        super().closeEvent(event)
