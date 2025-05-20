import os
import sys
import csv
import time
import logging
import numpy as np

from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QDockWidget,
    QWidget,
    QLabel,
    QTextEdit,
    QVBoxLayout,
    QSplitter,
    QStatusBar,
    QAction,
    QToolBar,
    QComboBox,
    QLineEdit,
    QDialog,
    QFormLayout,
    QDialogButtonBox,
    QSizePolicy,
    QFileDialog,
    QMessageBox,
)
from PyQt5.QtCore import (
    Qt,
    QTimer,
    pyqtSlot,
    QDateTime,
    QSize,
    QVariant,
)
from PyQt5.QtGui import QIcon, QKeySequence, QImage

# Check IC4 availability
_IC4_AVAILABLE = False
_IC4_INITIALIZED = False
_ic4_module = None
try:
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    if current_file_dir not in sys.path:
        sys.path.insert(0, current_file_dir)
    import prim_app

    _IC4_AVAILABLE = getattr(prim_app, "IC4_AVAILABLE", False)
    _IC4_INITIALIZED = getattr(prim_app, "IC4_INITIALIZED", False)
    if _IC4_INITIALIZED:
        import imagingcontrol4 as ic4_sdk

        _ic4_module = ic4_sdk
    logging.getLogger(__name__).info(
        "Successfully checked prim_app for IC4 flags in MainWindow. Initialized: %s",
        _IC4_INITIALIZED,
    )
except Exception as e:
    logging.getLogger(__name__).warning(f"IC4 check failed: {e}")

from threads.qtcamera_widget import QtCameraWidget
from threads.serial_thread import SerialThread
from recording import TrialRecorder
from utils import list_serial_ports

from control_panels.top_control_panel import TopControlPanel
from canvas.pressure_plot_widget import PressurePlotWidget

from config import (
    APP_NAME,
    APP_VERSION,
    ABOUT_TEXT,
    DEFAULT_FPS,
    DEFAULT_FRAME_SIZE,
    PRIM_RESULTS_DIR,
    DEFAULT_VIDEO_EXTENSION,
    DEFAULT_VIDEO_CODEC,
    SUPPORTED_FORMATS,
)

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._serial_thread = None
        self.trial_recorder = None
        self._is_recording = False
        self.last_trial_basepath = ""

        self.current_camera_frame_width = DEFAULT_FRAME_SIZE[0]
        self.current_camera_frame_height = DEFAULT_FRAME_SIZE[1]

        self._init_paths_and_icons()
        self._build_console_log_dock()
        self._build_central_widget_layout()
        self._build_menus()
        self._build_main_toolbar()
        self._build_status_bar()

        self.setWindowTitle(f"{APP_NAME} - v{APP_VERSION or '1.0'}")
        self.showMaximized()
        self.statusBar().showMessage(
            "Ready. Select camera (if available) and serial port.", 5000
        )

        self._set_initial_control_states()
        self._connect_top_control_panel_signals()
        self._connect_camera_widget_signals()

        # Populate camera list after a short delay
        if hasattr(self.top_ctrl, "camera_controls") and self.top_ctrl.camera_controls:
            QTimer.singleShot(250, self.top_ctrl.camera_controls.populate_camera_list)

    def _init_paths_and_icons(self):
        base = os.path.dirname(os.path.abspath(__file__))
        icon_dir = os.path.join(base, "icons")

        def get_icon(name):
            path = os.path.join(icon_dir, name)
            if not os.path.exists(path):
                log.warning(f"Icon not found: {path}")
                return QIcon()
            return QIcon(path)

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
        central_container_widget = QWidget()
        outer_layout = QVBoxLayout(central_container_widget)
        outer_layout.setContentsMargins(2, 2, 2, 2)
        outer_layout.setSpacing(3)

        self.top_ctrl = TopControlPanel(self)
        self.top_ctrl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        outer_layout.addWidget(self.top_ctrl)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)

        self.qt_cam_widget = QtCameraWidget(self)
        self.pressure_plot_widget = PressurePlotWidget(self)

        self.main_splitter.addWidget(self.qt_cam_widget)
        self.main_splitter.addWidget(self.pressure_plot_widget)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(0, 0)

        outer_layout.addWidget(self.main_splitter, 1)
        self.setCentralWidget(central_container_widget)

    def _build_menus(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&File")
        export_plot_data_action = QAction("Export Plot &Data (CSV)…", self)
        export_plot_data_action.triggered.connect(self._export_plot_data_as_csv)
        file_menu.addAction(export_plot_data_action)

        export_plot_image_action = QAction("Export Plot &Image…", self)
        export_plot_image_action.triggered.connect(
            self.pressure_plot_widget.export_as_image
        )
        file_menu.addAction(export_plot_image_action)
        file_menu.addSeparator()
        exit_action = QAction("&Exit", self, shortcut=QKeySequence.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        acq_menu = menubar.addMenu("&Acquisition")
        self.start_recording_action = QAction(
            self.icon_record_start,
            "Start &Recording",
            self,
            shortcut=Qt.CTRL | Qt.Key_R,
            triggered=self._trigger_start_recording_dialog,
            enabled=False,
        )
        acq_menu.addAction(self.start_recording_action)

        self.stop_recording_action = QAction(
            self.icon_record_stop,
            "Stop R&ecording",
            self,
            shortcut=Qt.CTRL | Qt.Key_T,
            triggered=self._trigger_stop_recording,
            enabled=False,
        )
        acq_menu.addAction(self.stop_recording_action)

        view_menu = menubar.addMenu("&View")
        view_menu.addAction(self.dock_console.toggleViewAction())

        plot_menu = menubar.addMenu("&Plot")
        clear_plot_action = QAction(
            "&Clear Plot Data", self, triggered=self._clear_pressure_plot
        )
        plot_menu.addAction(clear_plot_action)
        reset_plot_zoom_action = QAction(
            "&Reset Plot Zoom",
            self,
            triggered=lambda: self.pressure_plot_widget.reset_zoom(
                self.top_ctrl.plot_controls.auto_x_cb.isChecked(),
                self.top_ctrl.plot_controls.auto_y_cb.isChecked(),
            ),
        )
        plot_menu.addAction(reset_plot_zoom_action)

        help_menu = menubar.addMenu("&Help")
        about_app_action = QAction(
            f"&About {APP_NAME}", self, triggered=self._show_about_dialog
        )
        help_menu.addAction(about_app_action)
        help_menu.addAction("About &Qt", QApplication.instance().aboutQt)

    def _build_main_toolbar(self):
        toolbar = QToolBar("Main Controls")
        toolbar.setObjectName("MainControlsToolbar")
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        self.connect_serial_action = QAction(
            self.icon_connect,
            "&Connect PRIM Device",
            self,
            triggered=self._toggle_serial_connection,
        )
        toolbar.addAction(self.connect_serial_action)

        self.serial_port_combobox = QComboBox()
        self.serial_port_combobox.setToolTip("Select Serial Port for PRIM device")
        self.serial_port_combobox.setMinimumWidth(200)
        self.serial_port_combobox.addItem("🔌 Simulated Data", QVariant())
        ports = list_serial_ports()
        if ports:
            for port_path, desc in ports:
                self.serial_port_combobox.addItem(
                    f"{os.path.basename(port_path)} ({desc})", QVariant(port_path)
                )
        else:
            self.serial_port_combobox.addItem("No Serial Ports Found", QVariant())
            self.serial_port_combobox.setEnabled(False)
        toolbar.addWidget(self.serial_port_combobox)

        self.video_format_combobox = QComboBox()
        self.video_format_combobox.setToolTip("Select Video Recording Format")
        for fmt_str in SUPPORTED_FORMATS:
            self.video_format_combobox.addItem(fmt_str.upper(), QVariant(fmt_str))
        default_idx = self.video_format_combobox.findData(
            QVariant(DEFAULT_VIDEO_EXTENSION.lower())
        )
        if default_idx != -1:
            self.video_format_combobox.setCurrentIndex(default_idx)
        toolbar.addWidget(self.video_format_combobox)

        toolbar.addSeparator()
        toolbar.addAction(self.start_recording_action)
        toolbar.addAction(self.stop_recording_action)

    def _build_status_bar(self):
        status_bar = self.statusBar() or QStatusBar(self)
        self.setStatusBar(status_bar)

        self.app_session_time_label = QLabel("Session: 00:00:00")
        status_bar.addPermanentWidget(self.app_session_time_label)
        self._app_session_seconds = 0
        self._app_session_timer = QTimer(self, interval=1000)
        self._app_session_timer.timeout.connect(self._update_app_session_time)
        self._app_session_timer.start()

    def _set_initial_control_states(self):
        self.top_ctrl.update_connection_status("Disconnected", False)
        if hasattr(self.top_ctrl, "camera_controls") and self.top_ctrl.camera_controls:
            self.top_ctrl.camera_controls.disable_all_controls()
        self.start_recording_action.setEnabled(False)
        self.stop_recording_action.setEnabled(False)

    def _connect_top_control_panel_signals(self):
        tc = self.top_ctrl
        tc.camera_selected.connect(self._handle_camera_selection)
        tc.resolution_selected.connect(self._handle_resolution_selection)
        tc.exposure_changed.connect(lambda val: self.qt_cam_widget.set_exposure(val))
        tc.gain_changed.connect(lambda val: self.qt_cam_widget.set_gain(val))
        tc.auto_exposure_toggled.connect(
            lambda checked: self.qt_cam_widget.set_auto_exposure(checked)
        )
        tc.roi_changed.connect(self.qt_cam_widget.set_software_roi)
        tc.roi_reset_requested.connect(self.qt_cam_widget.reset_roi_to_default)

        pc = tc.plot_controls
        pc.x_axis_limits_changed.connect(self.pressure_plot_widget.set_manual_x_limits)
        pc.y_axis_limits_changed.connect(self.pressure_plot_widget.set_manual_y_limits)
        pc.export_plot_image_requested.connect(
            self.pressure_plot_widget.export_as_image
        )
        pc.reset_btn.clicked.connect(
            lambda: self.pressure_plot_widget.reset_zoom(
                pc.auto_x_cb.isChecked(), pc.auto_y_cb.isChecked()
            )
        )

    def _connect_camera_widget_signals(self):
        if hasattr(self.top_ctrl, "camera_controls") and self.top_ctrl.camera_controls:
            self.qt_cam_widget.camera_resolutions_updated.connect(
                self.top_ctrl.camera_controls.update_camera_resolutions_list
            )
            self.qt_cam_widget.camera_properties_updated.connect(
                self.top_ctrl.camera_controls.update_camera_properties_ui
            )
        self.qt_cam_widget.camera_error.connect(self._handle_camera_error)
        self.qt_cam_widget.frame_ready.connect(self._handle_new_camera_frame)

    @pyqtSlot(ic4_sdk.DeviceInfo)
    def _handle_camera_selection(self, device_info_obj):
        log.debug(
            f"MainWindow: Camera selection changed. DeviceInfo: {device_info_obj}"
        )
        is_ic4_device = (
            _ic4_module
            and hasattr(_ic4_module, "DeviceInfo")
            and isinstance(device_info_obj, _ic4_module.DeviceInfo)
        )
        if is_ic4_device:
            self.qt_cam_widget.set_active_camera_device(device_info_obj)
        else:
            self.qt_cam_widget.set_active_camera_device(None)
            if hasattr(self.top_ctrl, "camera_controls"):
                self.top_ctrl.camera_controls.disable_all_controls()
                self.top_ctrl.camera_controls.update_camera_resolutions_list([])
        self._update_recording_actions_enable_state()

    @pyqtSlot(str)
    def _handle_resolution_selection(self, resolution_str: str):
        log.debug(f"MainWindow: Resolution selection changed to: {resolution_str}")
        self.qt_cam_widget.set_active_resolution_str(resolution_str)
        try:
            if "x" in resolution_str:
                w_str, h_rest = resolution_str.split("x", 1)
                h_str = h_rest.split(" ")[0]
                self.current_camera_frame_width = int(w_str)
                self.current_camera_frame_height = int(h_str)
                log.info(
                    f"Recording frame size hint updated to {self.current_camera_frame_width}x{self.current_camera_frame_height}"
                )
        except Exception as e:
            log.warning(f"Could not parse resolution '{resolution_str}': {e}")

    @pyqtSlot(str, str)
    def _handle_camera_error(self, msg: str, code: str):
        log.error(f"Camera Error: {code} – {msg}")
        self.statusBar().showMessage(f"Camera Error: {msg}", 7000)
        if self._is_recording:
            QMessageBox.warning(
                self,
                "Recording Problem",
                f"A camera error occurred: {msg}\nRecording will stop.",
            )
            self._trigger_stop_recording()
        self._update_recording_actions_enable_state()

    def _toggle_serial_connection(self):
        if self._serial_thread and self._serial_thread.isRunning():
            log.info("Stopping serial thread...")
            self._serial_thread.stop()
        else:
            data = self.serial_port_combobox.currentData()
            port = data.value() if isinstance(data, QVariant) else data
            if (
                port is None
                and self.serial_port_combobox.currentText() != "🔌 Simulated Data"
            ):
                QMessageBox.warning(self, "Serial Connection", "Please select a port.")
                return

            log.info(f"Starting serial thread on port: {port or 'Simulation'}")
            try:
                if self._serial_thread and self._serial_thread.isRunning():
                    if not self._serial_thread.wait(100):
                        self._serial_thread.terminate()
                        self._serial_thread.wait(500)
                    self._serial_thread = None

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
            except Exception as e:
                log.exception("Failed to start SerialThread.")
                QMessageBox.critical(self, "Serial Error", str(e))
                self._serial_thread = None
                self._update_recording_actions_enable_state()

    @pyqtSlot(str)
    def _handle_serial_status_change(self, status: str):
        log.info(f"Serial status: {status}")
        self.statusBar().showMessage(f"PRIM Device: {status}", 4000)
        connected = "connected" in status.lower()
        self.top_ctrl.update_connection_status(status, connected)
        if connected:
            self.connect_serial_action.setIcon(self.icon_disconnect)
            self.connect_serial_action.setText("Disconnect PRIM Device")
            self.serial_port_combobox.setEnabled(False)
            self.pressure_plot_widget.clear_plot()
        else:
            self.connect_serial_action.setIcon(self.icon_connect)
            self.connect_serial_action.setText("Connect PRIM Device")
            self.serial_port_combobox.setEnabled(True)
            if self._is_recording:
                QMessageBox.information(
                    self, "Recording Stopped", "PRIM device disconnected."
                )
                self._trigger_stop_recording()
        self._update_recording_actions_enable_state()

    @pyqtSlot(str)
    def _handle_serial_error(self, msg: str):
        log.error(f"Serial error: {msg}")
        self.statusBar().showMessage(f"Serial Error: {msg}", 6000)

    @pyqtSlot()
    def _handle_serial_thread_finished(self):
        log.info("SerialThread finished.")
        if self._serial_thread is self.sender():
            self._serial_thread = None
            current = (
                self.top_ctrl.conn_lbl.text().lower()
                if hasattr(self.top_ctrl, "conn_lbl")
                else ""
            )
            if "connected" in current:
                self._handle_serial_status_change("Disconnected")
            else:
                self._update_recording_actions_enable_state()

    @pyqtSlot(int, float, float)
    def _handle_new_serial_data(self, idx: int, t: float, p: float):
        # Update GUI
        self.top_ctrl.update_prim_data(idx, t, p)
        ax = self.top_ctrl.plot_controls.auto_x_cb.isChecked()
        ay = self.top_ctrl.plot_controls.auto_y_cb.isChecked()
        self.pressure_plot_widget.update_plot(t, p, ax, ay)
        if self.dock_console.isVisible():
            self.console_out_textedit.append(
                f"PRIM Data: Idx={idx}, Time={t:.3f}s, P={p:.2f}"
            )

        # Write CSV if recording
        if self._is_recording and self.trial_recorder:
            try:
                self.trial_recorder.write_csv_data(t, idx, p)
            except Exception:
                log.exception("Error writing CSV during recording.")
                self.statusBar().showMessage(
                    "CSV write error. Stopping recording.", 5000
                )
                self._trigger_stop_recording()

    def _update_recording_actions_enable_state(self):
        serial_ready = (
            self._serial_thread is not None and self._serial_thread.isRunning()
        )
        camera_ready = self.qt_cam_widget.current_camera_is_active()

        can_start_recording = serial_ready and camera_ready and not self._is_recording

        # Use the correct variable and ensure a bool is passed
        self.start_recording_action.setEnabled(bool(can_start_recording))
        self.stop_recording_action.setEnabled(bool(self._is_recording))

    @pyqtSlot(QImage, object)
    def _handle_new_camera_frame(self, qimage: QImage, frame_obj: object):
        if (
            qimage.width() != self.current_camera_frame_width
            or qimage.height() != self.current_camera_frame_height
        ):
            self.current_camera_frame_width = qimage.width()
            self.current_camera_frame_height = qimage.height()
            log.info(f"Actual camera frame size: {qimage.width()}x{qimage.height()}")

        if self._is_recording and self.trial_recorder and not qimage.isNull():
            try:
                # Convert to numpy
                numpy_frame = None
                if qimage.format() == QImage.Format_Grayscale8:
                    ptr = qimage.constBits()
                    numpy_frame = np.array(
                        ptr.asarray(qimage.sizeInBytes()), dtype=np.uint8
                    )
                    numpy_frame = numpy_frame.reshape(qimage.height(), qimage.width())
                elif qimage.format() == QImage.Format_RGB888:
                    ptr = qimage.constBits()
                    numpy_frame = np.array(
                        ptr.asarray(qimage.sizeInBytes()), dtype=np.uint8
                    )
                    numpy_frame = numpy_frame.reshape(
                        qimage.height(), qimage.width(), 3
                    )

                if numpy_frame is not None:
                    self.trial_recorder.write_video_frame(numpy_frame.copy())
                else:
                    log.warning("Unsupported QImage format for video frame.")

            except Exception:
                log.exception("Error writing video frame.")
                self.statusBar().showMessage(
                    "Video write error. Stopping recording.", 5000
                )
                self._trigger_stop_recording()

    def _trigger_start_recording_dialog(self):
        if not (self._serial_thread and self._serial_thread.isRunning()):
            QMessageBox.warning(
                self, "Cannot Start Recording", "PRIM device not connected."
            )
            return
        if not self.qt_cam_widget.current_camera_is_active():
            QMessageBox.warning(self, "Cannot Start Recording", "Camera is not active.")
            return
        if self._is_recording:
            QMessageBox.information(self, "Recording Active", "Already recording.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Start New Recording Session")
        layout = QFormLayout(dialog)
        name_edit = QLineEdit(
            f"Session_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}"
        )
        layout.addRow("Session Name:", name_edit)
        operator_edit = QLineEdit()
        layout.addRow("Operator:", operator_edit)
        notes_edit = QTextEdit()
        notes_edit.setFixedHeight(80)
        layout.addRow("Notes:", notes_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return

        session = name_edit.text().strip() or name_edit.placeholderText()
        safe = "".join(
            c if c.isalnum() or c in (" ", "_", "-") else "_" for c in session
        ).rstrip()
        safe = safe.replace(" ", "_")

        folder = os.path.join(PRIM_RESULTS_DIR, safe)
        try:
            os.makedirs(folder, exist_ok=True)
        except Exception as e:
            log.error(f"Couldn’t create folder {folder}: {e}")
            QMessageBox.critical(self, "File Error", str(e))
            return

        base = os.path.join(folder, safe)
        self.last_trial_basepath = folder

        w, h = self.current_camera_frame_width, self.current_camera_frame_height
        if w <= 0 or h <= 0:
            log.warning("Invalid frame size, using default.")
            w, h = DEFAULT_FRAME_SIZE

        ext_data = self.video_format_combobox.currentData()
        video_ext = ext_data.value() if isinstance(ext_data, QVariant) else ext_data
        if not video_ext:
            video_ext = DEFAULT_VIDEO_EXTENSION.lower()
        codec = DEFAULT_VIDEO_CODEC

        log.info(f"Starting recording: {base}, {DEFAULT_FPS} FPS, {w}x{h}, {video_ext}")
        try:
            self.trial_recorder = TrialRecorder(
                basepath=base,
                fps=DEFAULT_FPS,
                frame_size=(w, h),
                video_ext=video_ext,
                video_codec=codec,
            )
            if not self.trial_recorder.is_recording:
                raise RuntimeError("Recorder failed to start.")
        except Exception as e:
            log.exception("Failed to initialize TrialRecorder.")
            QMessageBox.critical(self, "Recording Error", str(e))
            self.trial_recorder = None
            return

        self._is_recording = True
        self.start_recording_action.setIcon(self.icon_recording_active)
        self._update_recording_actions_enable_state()
        self.pressure_plot_widget.clear_plot()
        self.statusBar().showMessage(f"Recording Started: {safe}", 0)

    def _trigger_stop_recording(self):
        if not self._is_recording:
            return

        log.info("Stopping recording.")
        if self.trial_recorder:
            try:
                self.trial_recorder.stop()
                count = self.trial_recorder.video_frame_count
                self.statusBar().showMessage(f"Recording Stopped. {count} frames", 7000)
                reply = QMessageBox.information(
                    self,
                    "Recording Saved",
                    f"Saved to:\n{self.last_trial_basepath}\nOpen folder?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply == QMessageBox.Yes:
                    if sys.platform == "win32":
                        os.startfile(self.last_trial_basepath)
                    elif sys.platform == "darwin":
                        os.system(f'open "{self.last_trial_basepath}"')
                    else:
                        os.system(f'xdg-open "{self.last_trial_basepath}"')
            except Exception:
                log.exception("Error stopping recorder.")
                self.statusBar().showMessage("Error stopping recording.", 5000)
            finally:
                self.trial_recorder = None

        self._is_recording = False
        self.start_recording_action.setIcon(self.icon_record_start)
        self._update_recording_actions_enable_state()

    @pyqtSlot()
    def _clear_pressure_plot(self):
        self.pressure_plot_widget.clear_plot()
        self.statusBar().showMessage("Pressure plot cleared.", 3000)

    @pyqtSlot()
    def _export_plot_data_as_csv(self):
        if not self.pressure_plot_widget.times:
            QMessageBox.information(self, "No Plot Data", "Nothing to export.")
            return
        default_name = (
            f"plot_data_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}.csv"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Plot Data", default_name, "CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return
        try:
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["time_s", "pressure_mmHg"])
                for t, p in zip(
                    self.pressure_plot_widget.times, self.pressure_plot_widget.pressures
                ):
                    writer.writerow([f"{t:.6f}", f"{p:.6f}"])
            self.statusBar().showMessage(
                f"Plot data exported to {os.path.basename(path)}", 4000
            )
        except Exception:
            log.exception("Failed to export plot data.")
            QMessageBox.critical(self, "Export Error", "Could not save CSV.")

    @pyqtSlot()
    def _show_about_dialog(self):
        QMessageBox.about(self, f"About {APP_NAME}", ABOUT_TEXT)

    def _update_app_session_time(self):
        self._app_session_seconds += 1
        h = self._app_session_seconds // 3600
        m = (self._app_session_seconds % 3600) // 60
        s = self._app_session_seconds % 60
        self.app_session_time_label.setText(f"Session: {h:02}:{m:02}:{s:02}")

    def closeEvent(self, event):
        log.info(f"Close event received. Recording: {self._is_recording}")
        if self._is_recording:
            reply = QMessageBox.question(
                self,
                "Confirm Exit",
                "Recording is in progress. Stop and exit?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self._trigger_stop_recording()
            else:
                event.ignore()
                return

        if self._serial_thread and self._serial_thread.isRunning():
            log.info("Stopping serial thread on exit...")
            self._serial_thread.stop()
            if not self._serial_thread.wait(2000):
                self._serial_thread.terminate()
                self._serial_thread.wait(500)
            self._serial_thread = None

        log.info("Closing camera widget.")
        self.qt_cam_widget.close()
        super().closeEvent(event)
