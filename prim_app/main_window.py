# prim_app/main_window.py

import os
import sys
import re
import logging
import csv
import json
from datetime import datetime
import imagingcontrol4 as ic4

from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QSplitter,
    QFormLayout,
    QDockWidget,
    QTextEdit,
    QToolBar,
    QStatusBar,
    QAction,
    QFileDialog,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QComboBox,
    QLabel,
    QPushButton,
    QMessageBox,
    QSizePolicy,
    QTabWidget,
    QGroupBox,
    QDoubleSpinBox,
    QCheckBox,
    QHBoxLayout,
)
from PyQt5.QtCore import (
    Qt,
    pyqtSlot,
    QTimer,
    QVariant,
    QSize,
    QThread,
    QMetaObject,
)
from PyQt5.QtGui import QIcon, QKeySequence, QImage

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
    PLOT_DEFAULT_Y_MIN,
    PLOT_DEFAULT_Y_MAX,
)
from utils.path_helpers import get_next_fill_folder
from ui.canvas.qtcamera_widget import QtCameraWidget
from ui.control_panels.camera_control_panel import CameraControlPanel
from ui.control_panels.top_control_panel import TopControlPanel
from ui.control_panels.plot_control_panel import PlotControlPanel
from ui.canvas.pressure_plot_widget import PressurePlotWidget

from threads.serial_thread import SerialThread
from threads.sdk_camera_thread import SDKCameraThread
from recording_manager import RecordingManager
from utils.utils import list_serial_ports

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # ─── State Variables ─────────────────────────────────────────────────────
        self._serial_thread = None
        self._serial_active = False
        self._recorder_thread = None
        self._recorder_worker = None

        # Camera‐related
        self.device_combo = None
        self.resolution_combo = None
        self.btn_start_camera = None
        self.camera_widget = None
        self.camera_control_panel = None
        self.camera_tabs = None
        self.camera_thread = None  # SDKCameraThread instance

        # Plot controls
        self.plot_control_panel = None

        # Top control (Arduino status)
        self.top_ctrl = None

        # Plotting
        self.pressure_plot_widget = None

        # Other UI
        self.lbl_cam_connection = None
        self.lbl_cam_frame = None
        self.lbl_cam_resolution = None

        # ─── CREATE THE RECORDER THREAD + WORKER ─────────────────────────────────
        # 1) Instantiate the thread object:
        self._recorder_thread = QThread(self)

        dummy_output_dir = ""  # replace with a default or override later
        self._recorder_worker = RecordingManager(dummy_output_dir, use_ome=False)

        # 3) Move the worker into the new thread:
        self._recorder_worker.moveToThread(self._recorder_thread)

        # 4) Connect the worker’s finished signal → thread.quit() and cleanup:
        self._recorder_worker.finished.connect(self._recorder_thread.quit)
        self._recorder_worker.finished.connect(self._recorder_worker.deleteLater)
        self._recorder_thread.finished.connect(self._recorder_thread.deleteLater)


        self._init_paths_and_icons()
        self._build_console_log_dock()
        self._build_central_widget_layout()
        self._build_menus()
        self._build_main_toolbar()
        self._build_status_bar()

        # Populate device list so user can select camera
        self._populate_device_list()
        self._set_initial_control_states()

        self.setWindowTitle(f"{APP_NAME} - v{APP_VERSION}")
        QTimer.singleShot(50, self._set_initial_splitter_sizes)
        log.info("MainWindow initialized.")
        self.showMaximized()

    # ─── UI Builders ────────────────────────────────────────────────────────

    def _init_paths_and_icons(self):
        base = os.path.dirname(os.path.abspath(__file__))
        icon_dir = os.path.join(base, "ui", "icons")
        if not os.path.isdir(icon_dir):
            alt_icon_dir = os.path.join(
                os.path.dirname(base), "prim_app", "ui", "icons"
            )
            if os.path.isdir(alt_icon_dir):
                icon_dir = alt_icon_dir
            else:
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
        Top row: [Camera Info/Controls tabs] [TopControlPanel] [PlotControlPanel]
        Bottom row: [QtCameraWidget (live)] | [PressurePlotWidget (live plot)]
        """
        self.camera_widget = QtCameraWidget(self)

        central = QWidget()
        main_vlay = QVBoxLayout(central)
        main_vlay.setContentsMargins(4, 4, 4, 4)
        main_vlay.setSpacing(6)

        # ─── Top Row ──────────────────────────────────────────────────────
        top_row_widget = QWidget()
        top_row_lay = QHBoxLayout(top_row_widget)
        top_row_lay.setContentsMargins(0, 0, 0, 0)
        top_row_lay.setSpacing(10)

        # Camera Control Tabs (Info & Controls)
        self.camera_tabs = QTabWidget()
        self.camera_tabs.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

        # Info Tab
        info_tab = QWidget()
        info_layout = QFormLayout(info_tab)
        info_layout.setContentsMargins(6, 6, 6, 6)
        info_layout.setSpacing(4)

        self.lbl_cam_connection = QLabel("Disconnected")
        info_layout.addRow("Camera Status:", self.lbl_cam_connection)

        self.lbl_cam_frame = QLabel("0")
        info_layout.addRow("Frame #:", self.lbl_cam_frame)

        self.lbl_cam_resolution = QLabel("N/A")
        info_layout.addRow("Resolution:", self.lbl_cam_resolution)

        self.device_combo = QComboBox()
        self.device_combo.addItem("Select Device...", None)
        self.device_combo.currentIndexChanged.connect(self._on_device_selected)
        info_layout.addRow("Device:", self.device_combo)

        self.resolution_combo = QComboBox()
        self.resolution_combo.addItem("Select Resolution…", None)
        info_layout.addRow("Resolution:", self.resolution_combo)

        self.btn_start_camera = QPushButton("Start Camera")
        self.btn_start_camera.clicked.connect(self._on_start_stop_camera)
        info_layout.addRow("", self.btn_start_camera)

        self.camera_tabs.addTab(info_tab, "Info")

        # Controls Tab
        controls_tab = QWidget()
        controls_layout = QVBoxLayout(controls_tab)
        controls_layout.setContentsMargins(6, 6, 6, 6)
        controls_layout.setSpacing(6)

        # Instantiate CameraControlPanel here (disabled by default)
        self.camera_control_panel = CameraControlPanel(parent=self)
        self.camera_control_panel.setEnabled(False)
        controls_layout.addWidget(self.camera_control_panel)

        self.camera_tabs.addTab(controls_tab, "Controls")

        top_row_lay.addWidget(self.camera_tabs, stretch=2)

        # TopControlPanel (center)
        self.top_ctrl = TopControlPanel(self)
        self.top_ctrl.zero_requested.connect(self._on_zero_prim)
        top_row_lay.addWidget(self.top_ctrl, stretch=2)

        # PlotControlPanel (right)
        self.plot_control_panel = PlotControlPanel(self)
        top_row_lay.addWidget(self.plot_control_panel, stretch=2)

        main_vlay.addWidget(top_row_widget, stretch=0)

        # ─── Bottom Row ───────────────────────────────────────────────────
        self.bottom_split = QSplitter(Qt.Horizontal)
        self.bottom_split.setChildrenCollapsible(False)

        # Left: live viewfinder
        self.camera_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.bottom_split.addWidget(self.camera_widget)

        # Right: live plot
        self.pressure_plot_widget = PressurePlotWidget(self)
        self.pressure_plot_widget.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self.bottom_split.addWidget(self.pressure_plot_widget)

        self.bottom_split.setStretchFactor(0, 1)
        self.bottom_split.setStretchFactor(1, 1)

        main_vlay.addWidget(self.bottom_split, stretch=1)

        # ─── Wire Up PlotControlPanel → PressurePlotWidget ────────────────
        if hasattr(self.pressure_plot_widget, "set_auto_scale_x"):
            self.plot_control_panel.autoscale_x_changed.connect(
                self.pressure_plot_widget.set_auto_scale_x
            )
        if hasattr(self.pressure_plot_widget, "set_auto_scale_y"):
            self.plot_control_panel.autoscale_y_changed.connect(
                self.pressure_plot_widget.set_auto_scale_y
            )
        if hasattr(self.pressure_plot_widget, "set_manual_x_limits"):
            self.plot_control_panel.x_axis_limits_changed.connect(
                self.pressure_plot_widget.set_manual_x_limits
            )
        if hasattr(self.pressure_plot_widget, "set_manual_y_limits"):
            self.plot_control_panel.y_axis_limits_changed.connect(
                self.pressure_plot_widget.set_manual_y_limits
            )
        if hasattr(self.pressure_plot_widget, "reset_zoom"):
            self.plot_control_panel.reset_zoom_requested.connect(
                lambda: self.pressure_plot_widget.reset_zoom(
                    self.plot_control_panel.is_autoscale_x(),
                    self.plot_control_panel.is_autoscale_y(),
                )
            )
        if hasattr(self.pressure_plot_widget, "export_as_image"):
            self.plot_control_panel.export_plot_image_requested.connect(
                self.pressure_plot_widget.export_as_image
            )
        if hasattr(self.pressure_plot_widget, "clear_plot"):
            self.plot_control_panel.clear_plot_requested.connect(
                self.pressure_plot_widget.clear_plot
            )

        self.setCentralWidget(central)

    # ─── Camera Device & Resolution Enumeration ─────────────────────────────
    def _populate_device_list(self):
        try:
            device_list = ic4.DeviceEnum.devices()
        except Exception as e:
            log.error(f"Failed to enumerate IC4 devices: {e}")
            device_list = []

        if not device_list:
            log.info("DEBUG: DeviceEnum.devices() returned ZERO devices.")
        else:
            for idx, dev in enumerate(device_list):
                log.info(
                    f"DEBUG: Device {idx} = {dev.model_name!r} (S/N {dev.serial!r})"
                )

        self.device_combo.clear()
        self.device_combo.addItem("Select Device...", None)
        for dev in device_list:
            display_str = f"{dev.model_name}  (S/N: {dev.serial})"
            self.device_combo.addItem(display_str, dev)

    @pyqtSlot(int)
    def _on_device_selected(self, index):
        """
        Called whenever the user picks a different camera in the “Device” combo.
        Open it briefly, enumerate PixelFormat × (W,H), then close.
        """
        dev_info = self.device_combo.itemData(index)
        self.resolution_combo.clear()
        self.resolution_combo.addItem("Select Resolution…", None)

        if not dev_info:
            return

        grab = ic4.Grabber()
        try:
            grab.device_open(dev_info)

            # Force Continuous acquisition if possible
            acq_node = grab.device_property_map.find_enumeration("AcquisitionMode")
            if acq_node:
                names = [e.name for e in acq_node.entries]
                if "Continuous" in names:
                    acq_node.value = "Continuous"
                else:
                    acq_node.value = names[0]

            pf_node = grab.device_property_map.find_enumeration("PixelFormat")
            if pf_node:
                for entry in pf_node.entries:
                    pf_name = entry.name
                    try:
                        pf_node.value = pf_name
                        w_prop = grab.device_property_map.find_integer("Width")
                        h_prop = grab.device_property_map.find_integer("Height")
                        if w_prop and h_prop:
                            w = w_prop.value
                            h = h_prop.value
                            display_str = f"{w}×{h} ({pf_name})"
                            self.resolution_combo.addItem(display_str, (w, h, pf_name))
                    except Exception:
                        # skip any PF that fails
                        pass

        except Exception as e:
            log.error(f"Failed to get formats for {dev_info}: {e}")
        finally:
            try:
                grab.device_close()
            except Exception:
                pass

    @pyqtSlot()
    def _on_start_stop_camera(self):
        """
        Called when the user clicks “Start Camera” or “Stop Camera”.
        """
        if self.camera_thread is None or not self.camera_thread.isRunning():
            # ─── Start camera ─────────────────────────────────────────────────
            dev_info = self.device_combo.currentData()
            if dev_info is None:
                QMessageBox.warning(self, "Camera", "Please select a device first.")
                return

            resdata = self.resolution_combo.currentData()
            if not resdata:
                QMessageBox.warning(self, "Camera", "Please select a resolution first.")
                return

            w, h, pf_name = resdata

            # Instantiate the SDK camera thread
            self.camera_thread = SDKCameraThread(parent=self)
            self.camera_thread.set_device_info(dev_info)
            self.camera_thread.set_resolution((w, h, pf_name))

            # 1) When the grabber is open & streaming, enable the sliders, etc.
            self.camera_thread.grabber_ready.connect(self._on_grabber_ready)

            # 2) Each time a new frame is ready, update the QtCameraWidget
            self.camera_thread.frame_ready.connect(self.camera_widget._on_frame_ready)

            # 3) On any camera error, pop up a dialog and tear everything down
            self.camera_thread.error.connect(self._on_camera_error)

            # Show “Connecting…” in the Info tab
            self.lbl_cam_connection.setText("Connecting…")
            self.lbl_cam_frame.setText("0")
            self.lbl_cam_resolution.setText("N/A")

            # Actually start the thread
            self.camera_thread.start()
            self.btn_start_camera.setText("Stop Camera")
            self.camera_control_panel.setEnabled(False)

        else:
            # ─── Stop camera ──────────────────────────────────────────────────
            self.camera_thread.stop()
            self.camera_thread = None

            # Reset UI
            self.btn_start_camera.setText("Start Camera")
            self.camera_control_panel.setEnabled(False)
            self.lbl_cam_connection.setText("Disconnected")
            self.lbl_cam_frame.setText("0")
            self.lbl_cam_resolution.setText("N/A")
            self.camera_widget.clear_image()

    @pyqtSlot()
    def _on_grabber_ready(self):
        """
        Called once SDKCameraThread has opened the grabber and started streaming.
        We now hand the grabber over to CameraControlPanel to build its controls.
        """
        if self.camera_thread is None:
            return

        grabber = self.camera_thread.grabber
        if not grabber or not grabber.is_device_open:
            log.error("MainWindow: grabber_ready() arrived, but grabber is not open.")
            return

        self.camera_control_panel.grabber = grabber
        self.camera_control_panel._on_grabber_ready()
        self.camera_control_panel.setEnabled(True)

        self.lbl_cam_connection.setText("Connected")

    @pyqtSlot(QImage, object)
    def _update_camera_info(self, image: QImage, raw):
        """
        (Optional) Keep updating frame count & resolution in the “Info” tab
        every time a new frame arrives.  If you want to hook this up, simply:
            self.camera_thread.frame_ready.connect(self._update_camera_info)
        """
        try:
            current_count = int(self.lbl_cam_frame.text())
        except ValueError:
            current_count = 0
        current_count += 1
        self.lbl_cam_frame.setText(str(current_count))

        width = image.width()
        height = image.height()
        self.lbl_cam_resolution.setText(f"{width}×{height}")

        if self.lbl_cam_connection.text() != "Connected":
            self.lbl_cam_connection.setText("Connected")

    @pyqtSlot(str, str)
    def _on_camera_error(self, msg: str, code: str):
        """
        Show any camera‐related IC4 errors in a dialog, then reset UI to “off” state.
        """
        log.error(f"Camera error occurred ({code}): {msg}")
        QMessageBox.critical(self, "Camera Error", msg)

        # If the thread is still running, stop it
        if self.camera_thread and self.camera_thread.isRunning():
            try:
                self.camera_thread.stop()
            except Exception:
                pass

        self.camera_control_panel.setEnabled(False)
        self.lbl_cam_connection.setText("Error")
        self.lbl_cam_frame.setText("0")
        self.lbl_cam_resolution.setText("N/A")
        self.camera_widget.clear_image()
        self.btn_start_camera.setText("Start Camera")

    def _build_menus(self):
        mb = self.menuBar()
        fm = mb.addMenu("&File")
        exp_data_act = QAction(
            "Export Plot &Data (CSV)…", self, triggered=self._export_plot_data_as_csv
        )
        fm.addAction(exp_data_act)
        exp_img_act = QAction("Export Plot &Image…", self)
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
            triggered=self._on_start_recording,
            enabled=False,
        )
        am.addAction(self.start_recording_action)
        self.stop_recording_action = QAction(
            self.icon_record_stop,
            "Stop R&ecording",
            self,
            shortcut=Qt.CTRL | Qt.Key_T,
            triggered=self._on_stop_recording,
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
            if hasattr(self.pressure_plot_widget, "reset_zoom"):
                self.pressure_plot_widget.reset_zoom(
                    self.plot_control_panel.is_autoscale_x(),
                    self.plot_control_panel.is_autoscale_y(),
                )
            else:
                log.warning("reset_zoom() not found on PressurePlotWidget")

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

        # Serial port connect/disconnect
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
        ports = list_serial_ports()
        if ports:
            for p_dev, p_desc in ports:
                self.serial_port_combobox.addItem(
                    f"{os.path.basename(p_dev)} ({p_desc})", QVariant(p_dev)
                )
        else:
            self.serial_port_combobox.addItem("No Serial Ports Found", QVariant())
            self.serial_port_combobox.setEnabled(False)
        tb.addWidget(self.serial_port_combobox)
        tb.addSeparator()

        if hasattr(self, "start_recording_action"):
            tb.addAction(self.start_recording_action)
        if hasattr(self, "stop_recording_action"):
            tb.addAction(self.stop_recording_action)

    def _build_status_bar(self):
        sb = self.statusBar()
        self.app_session_time_label = QLabel("Session: 00:00:00")
        sb.addPermanentWidget(self.app_session_time_label)
        self._app_session_seconds = 0
        self._app_session_timer = QTimer(self)
        self._app_session_timer.setInterval(1000)
        self._app_session_timer.timeout.connect(self._update_app_session_time)
        self._app_session_timer.start()

    @pyqtSlot()
    def _update_app_session_time(self):
        """
        Increment the session timer (in seconds) and update the status‐bar label.
        """
        self._app_session_seconds += 1
        hours, rem = divmod(self._app_session_seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        self.app_session_time_label.setText(
            f"Session: {hours:02d}:{minutes:02d}:{seconds:02d}"
        )

    @pyqtSlot()
    def _clear_pressure_plot(self):
        if self.pressure_plot_widget and hasattr(
            self.pressure_plot_widget, "clear_plot"
        ):
            self.pressure_plot_widget.clear_plot()
            self.statusBar().showMessage("Pressure plot data cleared.", 3000)

    @pyqtSlot()
    def _on_zero_prim(self):
        """Send the zeroing command to the PRIM device and clear the plot."""
        try:
            # Clear the live pressure plot regardless of connection state
            if self.pressure_plot_widget and hasattr(
                self.pressure_plot_widget, "clear_plot"
            ):
                self.pressure_plot_widget.clear_plot()

            if self._serial_thread and self._serial_thread.isRunning():
                # Send the zero command when the PRIM device is connected
                self._serial_thread.send_command("Z")
                msg = "Zero command sent to PRIM and plot cleared."
            else:
                msg = "PRIM device not connected; plot cleared."

            self.statusBar().showMessage(msg, 3000)
        except Exception:
            log.exception("Failed to send zero command to Arduino")

    def _set_initial_splitter_sizes(self):
        if self.bottom_split:
            w = self.bottom_split.width()
            if w > 0:
                self.bottom_split.setSizes([int(w * 0.6), int(w * 0.4)])
            else:
                QTimer.singleShot(100, self._set_initial_splitter_sizes)

    def _set_initial_control_states(self):
        if hasattr(self, "start_recording_action"):
            self.start_recording_action.setEnabled(False)
        if hasattr(self, "stop_recording_action"):
            self.stop_recording_action.setEnabled(False)
        if hasattr(self, "camera_control_panel"):
            self.camera_control_panel.setEnabled(False)
        if hasattr(self, "plot_control_panel"):
            self.plot_control_panel.setEnabled(True)

    # ─── Menu Actions & Dialog Slots ──────────────────────────────────────────
    def _export_plot_data_as_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Plot Data as CSV", PRIM_RESULTS_DIR, "CSV Files (*.csv)"
        )
        if path:
            try:
                data = self.pressure_plot_widget.get_plot_data()  # assume method exists
                with open(path, "w", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(["Time (s)", "Pressure (mmHg)"])
                    for t, p in zip(data["time"], data["pressure"]):
                        writer.writerow([t, p])
                self.statusBar().showMessage(f"Plot data exported to {path}", 3000)
            except Exception as e:
                log.error(f"Error exporting CSV: {e}")
                QMessageBox.critical(
                    self, "Export Error", f"Failed to export CSV:\n{e}"
                )

    def _show_about_dialog(self):
        QMessageBox.information(self, f"About {APP_NAME}", ABOUT_TEXT)

    # ─── Toggle Serial Connection ────────────────────────────────────────────
    def _toggle_serial_connection(self):
        """
        Toggle between Connect/Disconnect purely based on whether self._serial_thread
        is running.  No extra flags needed.

        - If _serial_thread is None or not running → start a new SerialThread,
          immediately set the QAction to “Disconnect PRIM Device,” and disable the combo.
        - Otherwise (thread is running) → stop it, set _serial_thread = None,
          immediately flip QAction back to “Connect PRIM Device,” and re‐enable the combo.
        """
        # (1) If there is no running thread, go into “CONNECT” branch
        if self._serial_thread is None or not self._serial_thread.isRunning():
            # --- User clicked “Connect PRIM Device” ---
            data = self.serial_port_combobox.currentData()
            port = data.value() if isinstance(data, QVariant) else data

            if port is None:
                QMessageBox.warning(self, "Serial Connection", "Please select a port.")
                return

            log.info(f"Starting SerialThread on port: {port}")
            try:
                # If there is any leftover object, force‐stop and delete it
                if self._serial_thread:
                    if self._serial_thread.isRunning():
                        self._serial_thread.stop()
                        if not self._serial_thread.wait(1000):
                            self._serial_thread.terminate()
                            self._serial_thread.wait(500)
                    self._serial_thread.deleteLater()
                    self._serial_thread = None

                # Create and start the new thread
                self._serial_thread = SerialThread(port=port, parent=self)
                self._serial_thread.data_ready.connect(self._handle_new_serial_data)
                self._serial_thread.error_occurred.connect(self._handle_serial_error)
                self._serial_thread.status_changed.connect(
                    self._handle_serial_status_change
                )
                self._serial_thread.finished.connect(
                    self._handle_serial_thread_finished
                )
                self._serial_thread.start()

                # Immediately flip the QAction to “Disconnect PRIM Device”
                self.connect_serial_action.setIcon(self.icon_disconnect)
                self.connect_serial_action.setText("Disconnect PRIM Device")

                # Disable the combo so they can’t switch mid‐stream
                self.serial_port_combobox.setEnabled(False)

            except Exception as e:
                log.exception("Failed to start SerialThread.")
                QMessageBox.critical(self, "Serial Error", str(e))
                if self._serial_thread:
                    self._serial_thread.deleteLater()
                self._serial_thread = None
                # Re‐enable the combo in case it got disabled
                self.serial_port_combobox.setEnabled(True)
                self._refresh_recording_button_states()

        # (2) Otherwise, a thread is already running → go into “DISCONNECT” branch
        else:
            log.info("Stopping SerialThread on user request...")
            try:
                self._serial_thread.stop()
            except Exception as e:
                log.error(f"Error while stopping SerialThread: {e}")

            # Immediately flip QAction back to “Connect PRIM Device”
            self.connect_serial_action.setIcon(self.icon_connect)
            self.connect_serial_action.setText("Connect PRIM Device")

            # Re‐enable port-combo so they can pick another port
            self.serial_port_combobox.setEnabled(True)

            # Drop our reference so next click will “connect” again
            self._serial_thread = None

        # Finally, update the record‐button enable states (Start/Stop Recording)
        self._refresh_recording_button_states()

    @pyqtSlot(str)
    def _handle_serial_status_change(self, status: str):
        log.info(f"Serial status: {status}")
        self.statusBar().showMessage(f"PRIM Device: {status}", 4000)

        connected_flag = (
            "connected" in status.lower() or "opened serial port" in status.lower()
        )
        self.top_ctrl.update_connection_status(status, connected_flag)

        self._refresh_recording_button_states()

    @pyqtSlot(str)
    def _handle_serial_error(self, msg: str):
        log.error(f"Serial error: {msg}")
        # Show it in the status bar so user sees it
        self.statusBar().showMessage(f"Serial Error: {msg}", 6000)
        # Also re-evaluate whether the recording buttons are enabled
        self._refresh_recording_button_states()

    @pyqtSlot()
    def _handle_serial_thread_finished(self):
        log.info("SerialThread finished signal received.")
        sender = self.sender()

        if self._serial_thread is sender:
            # Clean up the thread object
            self._serial_thread.deleteLater()
            self._serial_thread = None

            # Immediately flip QAction back to “Connect PRIM Device”
            self.connect_serial_action.setIcon(self.icon_connect)
            self.connect_serial_action.setText("Connect PRIM Device")
            self.serial_port_combobox.setEnabled(True)

            log.info("SerialThread instance cleaned up.")
        else:
            log.warning(
                "Received 'finished' from an unknown/old SerialThread instance."
            )

        # Re‐evaluate “Start/Stop Recording” button states
        self._refresh_recording_button_states()

    @pyqtSlot(int, float, float)
    def _handle_new_serial_data(self, idx: int, t: float, p: float):
        """
        Called whenever SerialThread emits data_ready(idx, t, p).
        Pushes new data into TopControlPanel and the live plot.
        """
        # 1) Update TopControlPanel (frame count, device time, pressure)
        self.top_ctrl.update_prim_data(idx, t, p)

        # 2) Read the auto-scale checkboxes from PlotControlPanel
        ax = self.plot_control_panel.auto_x_cb.isChecked()
        ay = self.plot_control_panel.auto_y_cb.isChecked()

        # 3) Send the new sample to the PressurePlotWidget
        self.pressure_plot_widget.update_plot(t, p, ax, ay)

        # 4) Also log it to the console dock if visible
        if self.dock_console.isVisible():
            self.console_out_textedit.append(
                f"PRIM Data: Idx={idx}, Time={t:.3f}s, P={p:.2f}"
            )

    # ──────────────────────────────────────────────────────────────
    # Recording Management
    # ──────────────────────────────────────────────────────────────

    @pyqtSlot()
    def _on_start_recording(self):
        """
        Called when the user clicks ‘Start Recording’. Creates the next
        PRIM_ROOT/YYYY-MM-DD/FillN folder and starts a RecordingManager
        writing there.
        """
        outdir = get_next_fill_folder()

        fill_folder_name = os.path.basename(outdir)

        # Create the recording thread + worker exactly as before:
        self._recorder_thread = QThread(self)
        self._recorder_worker = RecordingManager(output_dir=outdir, use_ome=False)
        self._recorder_worker.moveToThread(self._recorder_thread)

        # 7) Wire up thread start → worker.start_recording()
        self._recorder_thread.started.connect(self._recorder_worker.start_recording)
        #    and worker.finished → thread.quit() + worker.deleteLater()
        self._recorder_worker.finished.connect(self._recorder_thread.quit)
        self._recorder_worker.finished.connect(self._recorder_worker.deleteLater)
        self._recorder_thread.finished.connect(self._recorder_thread.deleteLater)

        # 8) Hook camera + serial into the worker:
        self._serial_thread.data_ready.connect(self._recorder_worker.append_pressure)
        self.camera_thread.frame_ready.connect(self._recorder_worker.append_frame)

        # 9) Kick off the recording thread:
        self._recorder_thread.start()

        # Tell the Arduino to begin acquisition
        try:
            if self._serial_thread:
                self._serial_thread.send_command("G")
        except Exception:
            log.exception("Failed to send start command to Arduino")

        # Notify CameraControlPanel that recording has started
        if self.camera_control_panel:
            try:
                self.camera_control_panel.set_recording_state(True)
            except Exception:
                log.exception("Failed to set camera recording state to True")

        # 10) Update UI buttons (disable “Start” / enable “Stop”):
        self._refresh_recording_button_states()
        log.info(f"Recording started in {fill_folder_name}.")

    @pyqtSlot()
    def _on_stop_recording(self):
        """
        Called when the user clicks ‘Stop Recording’.
        Disconnects signals and tells the worker to stop.
        """
        # If there is no worker/thread, nothing to do.
        if not self._recorder_worker or not self._recorder_thread:
            return

        # Send stop command to the Arduino before disconnecting
        try:
            if self._serial_thread:
                self._serial_thread.send_command("S")
        except Exception:
            log.exception("Failed to send stop command to Arduino")

        # 1) Disconnect signals so no new data is queued
        try:
            self._serial_thread.data_ready.disconnect(
                self._recorder_worker.append_pressure
            )
        except Exception:
            pass

        try:
            self.camera_thread.frame_ready.disconnect(
                self._recorder_worker.append_frame
            )
        except Exception:
            pass

        # 2) When the worker actually finishes, clean up our Python references.
        def _cleanup_recorder():
            # At this point, worker has finished and thread has quit.
            # We can delete both and clear our Python handles:
            self._recorder_thread = None
            self._recorder_worker = None
            # If you need to update button states right away:
            self._refresh_recording_button_states()

        # Connect the worker’s finished → cleanup slot
        self._recorder_worker.finished.connect(_cleanup_recorder)
        # Also, when the thread actually quits, call deleteLater on both objects:
        self._recorder_worker.finished.connect(self._recorder_worker.deleteLater)
        self._recorder_thread.finished.connect(self._recorder_thread.deleteLater)

        # 3) Tell the worker to stop (it will flush & close files, then emit ‘finished’)
        QMetaObject.invokeMethod(
            self._recorder_worker, "stop_recording", Qt.QueuedConnection
        )

        # Notify CameraControlPanel that recording has stopped
        if self.camera_control_panel:
            try:
                self.camera_control_panel.set_recording_state(False)
            except Exception:
                log.exception("Failed to set camera recording state to False")

        # 4) Immediately update button states (the actual cleanup will happen in _cleanup_recorder)
        self._refresh_recording_button_states()
        log.info("Stop recording requested.")

    def _refresh_recording_button_states(self):
        """
        Enable “Start Recording” only if serial is connected and no recorder thread is running.
        Enable “Stop Recording” only if a RecordingManager thread is active.
        """
        serial_ready = (
            self._serial_thread is not None and self._serial_thread.isRunning()
        )
        recorder_running = (
            self._recorder_thread is not None and self._recorder_thread.isRunning()
        )
        can_start = serial_ready and not recorder_running
        can_stop = recorder_running

        self.start_recording_action.setEnabled(can_start)
        self.stop_recording_action.setEnabled(can_stop)

    # ─── Window Close Cleanup ──────────────────────────────────────────────────
    def closeEvent(self, event):
        log.info("MainWindow closeEvent triggered.")

        # 1) If RecordingManager is still running, request stop_recording() and wait.
        if self._recorder_worker and self._recorder_thread:
            if self._recorder_thread.isRunning():
                log.info("Stopping RecordingManager...")
                # Ask the worker to stop via queued call
                QMetaObject.invokeMethod(
                    self._recorder_worker, "stop_recording", Qt.QueuedConnection
                )
                # Wait up to 3 seconds for it to finish
                if not self._recorder_thread.wait(3000):
                    log.warning(
                        "RecordingManager thread did not stop gracefully; forcing terminate."
                    )
                    try:
                        self._recorder_thread.terminate()
                    except Exception:
                        pass
                    self._recorder_thread.wait(500)

        # Now that the thread is done, delete both worker and thread objects if they exist
        if self._recorder_worker:
            try:
                self._recorder_worker.deleteLater()
            except Exception:
                pass
            self._recorder_worker = None

        if self._recorder_thread:
            try:
                self._recorder_thread.deleteLater()
            except Exception:
                pass
            self._recorder_thread = None

        # 2) Stop the serial thread (if it exists)
        if self._serial_thread:
            try:
                if self._serial_thread.isRunning():
                    log.info("Stopping SerialThread...")
                    self._serial_thread.stop()  # assume your SerialThread has a stop() method
                    if not self._serial_thread.wait(1500):
                        log.warning(
                            "SerialThread did not stop gracefully; forcing terminate."
                        )
                        try:
                            self._serial_thread.terminate()
                        except Exception:
                            pass
                            self._serial_thread.wait(500)
            except RuntimeError:
                # The QThread object might already be deleted; ignore
                pass
            finally:
                try:
                    self._serial_thread.deleteLater()
                except Exception:
                    pass
                self._serial_thread = None

        # 3) Stop the camera thread (if it exists)
        cam_thread = self.camera_thread
        if cam_thread:
            try:
                if cam_thread.isRunning():
                    log.info("Stopping SDKCameraThread...")
                    cam_thread.stop()  # assume your SDKCameraThread has a stop() method
                    if not cam_thread.wait(1500):
                        log.warning(
                            "SDKCameraThread did not stop gracefully; forcing terminate."
                        )
                        try:
                            cam_thread.terminate()
                        except Exception:
                            pass
                        cam_thread.wait(500)
            except RuntimeError:
                # The QThread object might already be deleted; ignore
                pass
            finally:
                try:
                    cam_thread.deleteLater()
                except Exception:
                    pass
                self.camera_thread = None

        # 4) Clear UI elements that might hold references
        try:
            self.device_combo.clear()
        except Exception:
            pass

        # 5) Process any remaining events, then call the base implementation
        QApplication.processEvents()
        log.info("All threads cleaned up. Proceeding with close.")
        super().closeEvent(event)
