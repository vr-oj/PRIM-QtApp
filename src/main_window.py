import os
import sys
import csv
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

# Check for IC4 availability
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
        "Successfully checked prim_app for IC4 flags. Initialized: %s", _IC4_INITIALIZED
    )
except Exception as e:
    logging.getLogger(__name__).warning(f"MainWindow: Error checking IC4 status: {e}")

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

        # Track actual frame size
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

        # Populate camera list after UI ready
        if self.top_ctrl.camera_controls:
            QTimer.singleShot(250, self.top_ctrl.camera_controls.populate_camera_list)

    def _init_paths_and_icons(self):
        base = os.path.dirname(os.path.abspath(__file__))
        icon_dir = os.path.join(base, "icons")

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
        w = QWidget()
        layout = QVBoxLayout(w)
        self.console_out_textedit = QTextEdit(readOnly=True)
        self.console_out_textedit.setFontFamily("monospace")
        layout.addWidget(self.console_out_textedit)
        self.dock_console.setWidget(w)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.dock_console)
        self.dock_console.setVisible(False)

    def _build_central_widget_layout(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(3)
        self.top_ctrl = TopControlPanel(self)
        self.top_ctrl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self.top_ctrl)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.qt_cam_widget = QtCameraWidget(self)
        self.pressure_plot_widget = PressurePlotWidget(self)
        self.main_splitter.addWidget(self.qt_cam_widget)
        self.main_splitter.addWidget(self.pressure_plot_widget)
        self.main_splitter.setStretchFactor(0, 2)
        self.main_splitter.setStretchFactor(1, 3)
        layout.addWidget(self.main_splitter, 1)

        self.setCentralWidget(container)

    def _build_menus(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&File")
        act_export_csv = QAction("Export Plot &Data (CSV)…", self)
        act_export_csv.triggered.connect(self._export_plot_data_as_csv)
        file_menu.addAction(act_export_csv)
        act_export_img = QAction("Export Plot &Image…", self)
        act_export_img.triggered.connect(self.pressure_plot_widget.export_as_image)
        file_menu.addAction(act_export_img)
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
        clear_plot = QAction(
            "&Clear Plot Data", self, triggered=self._clear_pressure_plot
        )
        plot_menu.addAction(clear_plot)
        reset_zoom = QAction(
            "&Reset Plot Zoom",
            self,
            triggered=lambda: self.pressure_plot_widget.reset_zoom(
                self.top_ctrl.plot_controls.auto_x_cb.isChecked(),
                self.top_ctrl.plot_controls.auto_y_cb.isChecked(),
            ),
        )
        plot_menu.addAction(reset_zoom)

        help_menu = menubar.addMenu("&Help")
        about_app = QAction(
            f"&About {APP_NAME}", self, triggered=self._show_about_dialog
        )
        help_menu.addAction(about_app)
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
        for fmt in SUPPORTED_FORMATS:
            self.video_format_combobox.addItem(fmt.upper(), QVariant(fmt))
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
        self.top_ctrl.camera_controls.disable_all_controls()
        self.start_recording_action.setEnabled(False)
        self.stop_recording_action.setEnabled(False)

    def _connect_top_control_panel_signals(self):
        tc = self.top_ctrl
        tc.camera_selected.connect(self._handle_camera_selection)
        tc.resolution_selected.connect(self._handle_resolution_selection)
        tc.exposure_changed.connect(lambda v: self.qt_cam_widget.set_exposure(v))
        tc.gain_changed.connect(lambda v: self.qt_cam_widget.set_gain(v))
        tc.auto_exposure_toggled.connect(
            lambda b: self.qt_cam_widget.set_auto_exposure(b)
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
        cp = self.top_ctrl.camera_controls
        self.qt_cam_widget.camera_resolutions_updated.connect(
            cp.update_camera_resolutions_list
        )
        self.qt_cam_widget.camera_properties_updated.connect(
            cp.update_camera_properties_ui
        )
        self.qt_cam_widget.camera_error.connect(self._handle_camera_error)
        self.qt_cam_widget.frame_ready.connect(self._handle_new_camera_frame)

    @pyqtSlot(object)
    def _handle_camera_selection(self, device_info_obj):
        log.debug(f"Camera selection changed: {device_info_obj}")
        is_ic4 = _ic4_module and isinstance(device_info_obj, _ic4_module.DeviceInfo)
        if is_ic4:
            self.qt_cam_widget.set_active_camera_device(device_info_obj)
        else:
            self.qt_cam_widget.set_active_camera_device(None)
            self.top_ctrl.camera_controls.disable_all_controls()
            self.top_ctrl.camera_controls.update_camera_resolutions_list([])
        self._update_recording_actions_enable_state()

    @pyqtSlot(str)
    def _handle_resolution_selection(self, resolution_str: str):
        log.debug(f"Resolution selection: {resolution_str}")
        self.qt_cam_widget.set_active_resolution_str(resolution_str)
        try:
            w_str, h_rest = resolution_str.split("x", 1)
            w = int(w_str)
            h = int(h_rest.split()[0])
            self.current_camera_frame_width = w
            self.current_camera_frame_height = h
            log.info(f"Updated frame hint: {w}x{h}")
        except Exception as e:
            log.warning(f"Could not parse resolution: {e}")

    @pyqtSlot(str, str)
    def _handle_camera_error(self, message: str, code: str):
        log.error(f"Camera Error: {code} - {message}")
        self.statusBar().showMessage(f"Camera Error: {code}", 7000)
        if self._is_recording:
            QMessageBox.warning(
                self,
                "Recording Problem",
                f"Camera error occurred: {message}\nRecording will be stopped.",
            )
            self._trigger_stop_recording()
        self._update_recording_actions_enable_state()

    def _toggle_serial_connection(self):
        if self._serial_thread and self._serial_thread.isRunning():
            self._serial_thread.stop()
        else:
            data = self.serial_port_combobox.currentData()
            port_path = data.value() if isinstance(data, QVariant) else data
            if (
                port_path is None
                and self.serial_port_combobox.currentText() != "🔌 Simulated Data"
            ):
                QMessageBox.warning(
                    self, "Serial Connection", "Please select a valid serial port."
                )
                return
            try:
                if self._serial_thread and self._serial_thread.isRunning():
                    self._serial_thread.terminate()
                self._serial_thread = SerialThread(port=port_path, parent=self)
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
                log.exception("Failed to start serial thread.")
                QMessageBox.critical(
                    self, "Serial Error", f"Could not start serial communication: {e}"
                )
                self._serial_thread = None
            self._update_recording_actions_enable_state()

    @pyqtSlot(str)
    def _handle_serial_status_change(self, status_message: str):
        log.info(f"Serial status: {status_message}")
        self.top_ctrl.update_connection_status(
            status_message, "connected" in status_message.lower()
        )
        if "connected" in status_message.lower():
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
                    self,
                    "Recording Stopped",
                    "PRIM device disconnected. Recording has been stopped.",
                )
                self._trigger_stop_recording()
        self._update_recording_actions_enable_state()

    @pyqtSlot(str)
    def _handle_serial_error(self, error_message: str):
        log.error(f"Serial Error: {error_message}")
        self.statusBar().showMessage(f"PRIM Device Error: {error_message}", 6000)

    @pyqtSlot()
    def _handle_serial_thread_finished(self):
        if self._serial_thread is self.sender():
            self._serial_thread = None
            self._update_recording_actions_enable_state()

    @pyqtSlot(int, float, float)
    def _handle_new_serial_data(self, frame_idx: int, time_s: float, pressure: float):
        self.top_ctrl.update_prim_data(frame_idx, time_s, pressure)
        auto_x = self.top_ctrl.plot_controls.auto_x_cb.isChecked()
        auto_y = self.top_ctrl.plot_controls.auto_y_cb.isChecked()
        self.pressure_plot_widget.update_plot(time_s, pressure, auto_x, auto_y)
        if self.dock_console.isVisible():
            self.console_out_textedit.append(
                f"PRIM Data: Idx={frame_idx}, Time={time_s:.3f}s, Pressure={pressure:.2f} mmHg"
            )
        if self._is_recording and self.trial_recorder:
            try:
                self.trial_recorder.write_csv_data(time_s, frame_idx, pressure)
            except Exception as e:
                log.exception("Failed to write CSV data during recording.")
                self.statusBar().showMessage(
                    "Error writing CSV data. Recording stopped.", 5000
                )
                self._trigger_stop_recording()

    def _update_recording_actions_enable_state(self):
        serial_ready = self._serial_thread and self._serial_thread.isRunning()
        camera_ready = self.qt_cam_widget.current_camera_is_active()
        can_start = serial_ready and camera_ready and not self._is_recording
        self.start_recording_action.setEnabled(can_start)
        self.stop_recording_action.setEnabled(self._is_recording)

    @pyqtSlot(QImage, object)
    def _handle_new_camera_frame(self, qimage: QImage, frame_obj: object):
        if qimage and not qimage.isNull():
            if (
                self.current_camera_frame_width != qimage.width()
                or self.current_camera_frame_height != qimage.height()
            ):
                self.current_camera_frame_width = qimage.width()
                self.current_camera_frame_height = qimage.height()
                log.info(f"Actual frame size: {qimage.width()}x{qimage.height()}")
        if (
            self._is_recording
            and self.trial_recorder
            and qimage
            and not qimage.isNull()
        ):
            numpy_frame = None
            try:
                if qimage.format() == QImage.Format_Grayscale8:
                    ptr = qimage.constBits()
                    dims = (qimage.height(), qimage.width())
                    numpy_frame = np.array(
                        ptr.asarray(qimage.sizeInBytes()), dtype=np.uint8
                    ).reshape(dims)
                elif qimage.format() == QImage.Format_RGB888:
                    ptr = qimage.constBits()
                    dims = (qimage.height(), qimage.width(), 3)
                    numpy_frame = np.array(
                        ptr.asarray(qimage.sizeInBytes()), dtype=np.uint8
                    ).reshape(dims)
                if numpy_frame is not None:
                    self.trial_recorder.write_video_frame(numpy_frame.copy())
                else:
                    log.warning(
                        f"Unsupported QImage format for recording: {qimage.format()}"
                    )
            except Exception:
                log.exception("Failed to write video frame during recording.")
                self.statusBar().showMessage(
                    "Error writing video frame. Recording stopped.", 5000
                )
                self._trigger_stop_recording()

    def _trigger_start_recording_dialog(self):
        if not (self._serial_thread and self._serial_thread.isRunning()):
            QMessageBox.warning(
                self, "Cannot Start Recording", "PRIM device is not connected."
            )
            return
        if not self.qt_cam_widget.current_camera_is_active():
            QMessageBox.warning(
                self, "Cannot Start Recording", "Camera is not active or not selected."
            )
            return
        if self._is_recording:
            QMessageBox.information(
                self, "Recording Active", "Recording is already in progress."
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Start New Recording Session")
        layout = QFormLayout(dialog)
        name_edit = QLineEdit(
            f"Session_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}"
        )
        layout.addRow("Session Name:", name_edit)
        op_edit = QLineEdit()
        layout.addRow("Operator:", op_edit)
        notes_edit = QTextEdit()
        notes_edit.setFixedHeight(80)
        layout.addRow("Notes:", notes_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec_() != QDialog.Accepted:
            return

        session_name = name_edit.text().strip() or name_edit.placeholderText()
        safe_name = "".join(
            c if c.isalnum() or c in ("_", "-") else "_" for c in session_name
        ).rstrip()
        session_folder = os.path.join(PRIM_RESULTS_DIR, safe_name)
        os.makedirs(session_folder, exist_ok=True)
        base_output = os.path.join(session_folder, safe_name)
        self.last_trial_basepath = session_folder

        frame_w = self.current_camera_frame_width or DEFAULT_FRAME_SIZE[0]
        frame_h = self.current_camera_frame_height or DEFAULT_FRAME_SIZE[1]
        data = self.video_format_combobox.currentData()
        ext = data.value() if isinstance(data, QVariant) else data
        ext = ext or DEFAULT_VIDEO_EXTENSION.lower()
        codec = DEFAULT_VIDEO_CODEC

        try:
            self.trial_recorder = TrialRecorder(
                basepath=base_output,
                fps=DEFAULT_FPS,
                frame_size=(frame_w, frame_h),
                video_ext=ext,
                video_codec=codec,
            )
            if not self.trial_recorder.is_recording:
                raise RuntimeError("Recorder failed to start.")
        except Exception as e:
            log.exception("Failed to initialize recorder.")
            QMessageBox.critical(
                self, "Recording Error", f"Could not start recorder: {e}"
            )
            self.trial_recorder = None
            return

        self._is_recording = True
        self.start_recording_action.setIcon(self.icon_recording_active)
        self._update_recording_actions_enable_state()
        self.pressure_plot_widget.clear_plot()
        self.statusBar().showMessage(f"Recording Started: {safe_name}", 0)

    def _trigger_stop_recording(self):
        if not self._is_recording:
            return
        log.info("Stopping recording.")
        if self.trial_recorder:
            try:
                self.trial_recorder.stop()
                frames = self.trial_recorder.video_frame_count
                self.statusBar().showMessage(
                    f"Recording Stopped. Frames: {frames}", 7000
                )
                if self.last_trial_basepath and os.path.exists(
                    self.last_trial_basepath
                ):
                    reply = QMessageBox.information(
                        self,
                        "Recording Saved",
                        f"Recording saved to:\n{self.last_trial_basepath}\n\nOpen folder?",
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
                self.statusBar().showMessage("Error stopping recorder.", 5000)
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
            QMessageBox.information(self, "No Plot Data", "There is no data to export.")
            return
        default = (
            f"plot_data_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}.csv"
        )
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Plot Data as CSV", default, "CSV Files (*.csv);;All Files (*)"
        )
        if not file_path:
            return
        try:
            with open(file_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["time_s", "pressure_mmHg"])
                for t, p in zip(
                    self.pressure_plot_widget.times, self.pressure_plot_widget.pressures
                ):
                    writer.writerow([f"{t:.6f}", f"{p:.6f}"])
            self.statusBar().showMessage(
                f"Plot data exported to {os.path.basename(file_path)}", 4000
            )
        except Exception:
            log.exception("Failed to export plot data.")
            QMessageBox.critical(self, "Export Error", f"Could not save plot data: {e}")

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
        log.info(f"Closing MainWindow. Recording? {self._is_recording}")
        if self._is_recording:
            reply = QMessageBox.question(
                self,
                "Confirm Exit",
                "Recording in progress. Stop and exit?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self._trigger_stop_recording()
            else:
                event.ignore()
                return
        if self._serial_thread and self._serial_thread.isRunning():
            self._serial_thread.stop()
            self._serial_thread.wait(2000)
        self.qt_cam_widget.close()
        super().closeEvent(event)
