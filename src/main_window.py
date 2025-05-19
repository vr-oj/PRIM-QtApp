import os
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

_IC4_AVAILABLE = False
_IC4_INITIALIZED = False
_ic4_module = None

try:
    import sys

    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    if (
        current_file_dir not in sys.path
    ):  # Ensure current dir (src) is in path for prim_app
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

except ImportError as e:
    logging.getLogger(__name__).warning(
        f"MainWindow: Could not import 'prim_app' module to check IC4 status: {e}."
    )
except AttributeError as e:
    logging.getLogger(__name__).warning(
        f"MainWindow: 'prim_app' module imported, but flags missing: {e}."
    )
except Exception as e:
    logging.getLogger(__name__).error(
        f"MainWindow: Unexpected error during prim_app import for IC4 flags: {e}"
    )


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

        self.setWindowTitle(
            f"{APP_NAME} - v{APP_VERSION if 'APP_VERSION' in globals() and APP_VERSION else '1.0'}"
        )
        self.showMaximized()
        self.statusBar().showMessage(
            "Ready. Select camera (if available) and serial port.", 5000
        )

        self._set_initial_control_states()
        self._connect_top_control_panel_signals()
        self._connect_camera_widget_signals()

        if (
            hasattr(self.top_ctrl, "camera_controls")
            and self.top_ctrl.camera_controls is not None
        ):
            QTimer.singleShot(250, self.top_ctrl.camera_controls.populate_camera_list)
        else:
            log.error(
                "TopControlPanel or CameraControlPanel not initialized. Camera list might not populate."
            )

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
        self.main_splitter.setStretchFactor(0, 2)
        self.main_splitter.setStretchFactor(1, 3)

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
        self.serial_port_combobox.addItem(
            "🔌 Simulated Data", QVariant()
        )  # Store QVariant() for None
        ports = list_serial_ports()
        if ports:
            for port_path, desc in ports:
                # Store the actual port_path (string) as data, wrapped in QVariant
                self.serial_port_combobox.addItem(
                    f"{os.path.basename(port_path)} ({desc})", QVariant(port_path)
                )
        else:
            self.serial_port_combobox.addItem(
                "No Serial Ports Found", QVariant()
            )  # Store QVariant()
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
        if (
            hasattr(self.top_ctrl, "camera_controls")
            and self.top_ctrl.camera_controls is not None
        ):
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

        pc_controls = tc.plot_controls
        pc_controls.x_axis_limits_changed.connect(
            self.pressure_plot_widget.set_manual_x_limits
        )
        pc_controls.y_axis_limits_changed.connect(
            self.pressure_plot_widget.set_manual_y_limits
        )
        pc_controls.export_plot_image_requested.connect(
            self.pressure_plot_widget.export_as_image
        )
        pc_controls.reset_btn.clicked.connect(
            lambda: self.pressure_plot_widget.reset_zoom(
                pc_controls.auto_x_cb.isChecked(), pc_controls.auto_y_cb.isChecked()
            )
        )

    def _connect_camera_widget_signals(self):
        if (
            hasattr(self.top_ctrl, "camera_controls")
            and self.top_ctrl.camera_controls is not None
        ):
            self.qt_cam_widget.camera_resolutions_updated.connect(
                self.top_ctrl.camera_controls.update_camera_resolutions_list
            )
            self.qt_cam_widget.camera_properties_updated.connect(
                self.top_ctrl.camera_controls.update_camera_properties_ui
            )
        else:
            log.error(
                "Cannot connect camera widget signals: top_ctrl.camera_controls not found."
            )

        self.qt_cam_widget.camera_error.connect(self._handle_camera_error)
        self.qt_cam_widget.frame_ready.connect(self._handle_new_camera_frame)

    @pyqtSlot(object)
    def _handle_camera_selection(self, device_info_obj):
        log.debug(
            f"MainWindow: Camera selection changed. DeviceInfo: {device_info_obj}"
        )

        is_ic4_device = False
        if (
            _ic4_module
            and hasattr(_ic4_module, "DeviceInfo")
            and isinstance(device_info_obj, _ic4_module.DeviceInfo)
        ):
            is_ic4_device = True

        if is_ic4_device:
            self.qt_cam_widget.set_active_camera_device(device_info_obj)
        elif device_info_obj is None:
            self.qt_cam_widget.set_active_camera_device(None)
            if hasattr(self.top_ctrl, "camera_controls"):
                self.top_ctrl.camera_controls.disable_all_controls()
                self.top_ctrl.camera_controls.update_camera_resolutions_list([])
        else:
            log.warning(
                f"MainWindow: Received unknown camera data type: {type(device_info_obj)}"
            )
            self.qt_cam_widget.set_active_camera_device(None)

        self._update_recording_actions_enable_state()

    @pyqtSlot(str)
    def _handle_resolution_selection(self, resolution_str: str):
        log.debug(f"MainWindow: Resolution selection changed to: {resolution_str}")
        self.qt_cam_widget.set_active_resolution_str(resolution_str)
        try:
            if "x" in resolution_str:
                parts = resolution_str.split("x")
                self.current_camera_frame_width = int(parts[0])
                h_part = parts[1].split(" ")[0]
                self.current_camera_frame_height = int(h_part)
                log.info(
                    f"Recording frame size hint updated to {self.current_camera_frame_width}x{self.current_camera_frame_height}"
                )
        except Exception as e:
            log.warning(
                f"Could not parse resolution string '{resolution_str}' for frame size hint: {e}"
            )

    @pyqtSlot(str, str)
    def _handle_camera_error(self, error_message: str, error_code_str: str):
        log.error(
            f"MainWindow: Camera Error Received - Code: {error_code_str}, Message: {error_message}"
        )
        self.statusBar().showMessage(
            f"Camera Error: {error_code_str} - {error_message[:50]}...", 7000
        )
        if self._is_recording:
            QMessageBox.warning(
                self,
                "Recording Problem",
                f"Camera error occurred: {error_message}\nRecording will be stopped.",
            )
            self._trigger_stop_recording()
        self._update_recording_actions_enable_state()

    def _toggle_serial_connection(self):
        if self._serial_thread and self._serial_thread.isRunning():
            log.info("MainWindow: Attempting to stop serial thread.")
            self._serial_thread.stop()
        else:
            # --- THIS IS THE CORRECTED PART for AttributeError ---
            current_data = self.serial_port_combobox.currentData()
            port_path = None
            if isinstance(current_data, QVariant):  # Check if it's a QVariant
                port_path = current_data.value()  # If so, get its Python value
            else:  # Otherwise, assume currentData() returned the Python object directly
                port_path = current_data
            # port_path will now be the string or None, not a QVariant wrapping None

            if (
                port_path is None
                and self.serial_port_combobox.currentText() != "🔌 Simulated Data"
            ):
                QMessageBox.warning(
                    self, "Serial Connection", "Please select a valid serial port."
                )
                return

            log.info(
                f"MainWindow: Attempting to start serial thread for port: {port_path if port_path else 'Simulation'}"
            )
            try:
                if self._serial_thread:
                    if self._serial_thread.isRunning():
                        if not self._serial_thread.wait(100):
                            log.warning(
                                "Previous serial thread instance still running, terminating before starting new."
                            )
                            self._serial_thread.terminate()
                            self._serial_thread.wait(500)
                    self._serial_thread = None

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
                log.exception("MainWindow: Failed to create or start SerialThread.")
                QMessageBox.critical(
                    self, "Serial Error", f"Could not start serial communication: {e}"
                )
                self._serial_thread = None
                self._update_recording_actions_enable_state()

    @pyqtSlot(str)
    def _handle_serial_status_change(self, status_message: str):
        log.info(f"MainWindow: Serial status changed - {status_message}")
        self.statusBar().showMessage(f"PRIM Device: {status_message}", 4000)

        is_connected = "connected" in status_message.lower()
        self.top_ctrl.update_connection_status(status_message, is_connected)

        if is_connected:
            self.connect_serial_action.setIcon(self.icon_disconnect)
            self.connect_serial_action.setText("Disconnect PRIM Device")
            self.serial_port_combobox.setEnabled(False)
            self.pressure_plot_widget.clear_plot()
        else:
            self.connect_serial_action.setIcon(self.icon_connect)
            self.connect_serial_action.setText("Connect PRIM Device")
            self.serial_port_combobox.setEnabled(True)

            if self._is_recording:
                if "error" in status_message.lower():
                    QMessageBox.warning(
                        self,
                        "Recording Stopped",
                        f"PRIM device disconnected due to an error: {status_message}\nRecording has been stopped.",
                    )
                else:
                    QMessageBox.information(
                        self,
                        "Recording Stopped",
                        "PRIM device disconnected.\nRecording has been stopped.",
                    )
                self._trigger_stop_recording()

        self._update_recording_actions_enable_state()

    @pyqtSlot(str)
    def _handle_serial_error(self, error_message: str):
        log.error(f"MainWindow: Serial Error Received - {error_message}")
        self.statusBar().showMessage(f"PRIM Device Error: {error_message}", 6000)

    @pyqtSlot()
    def _handle_serial_thread_finished(self):
        log.info("MainWindow: SerialThread has finished.")
        if self._serial_thread is self.sender():
            self._serial_thread = None
            current_status_text = ""
            if hasattr(self.top_ctrl, "conn_lbl"):
                current_status_text = self.top_ctrl.conn_lbl.text().lower()
            if "connected" in current_status_text:
                self._handle_serial_status_change("Disconnected (thread finished)")
            else:
                self._update_recording_actions_enable_state()
            log.debug("MainWindow: _serial_thread dereferenced.")

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
                log.exception("MainWindow: Failed to write CSV data during recording.")
                self.statusBar().showMessage(
                    "Error writing CSV data. Recording stopped.", 5000
                )
                self._trigger_stop_recording()

    def _update_recording_actions_enable_state(self):
        serial_ready = (
            self._serial_thread is not None and self._serial_thread.isRunning()
        )
        camera_ready = self.qt_cam_widget.current_camera_is_active()

        can_start_recording = serial_ready and camera_ready and not self._is_recording

        self.start_recording_action.setEnabled(bool(can_start_recording))
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
                log.info(
                    f"MainWindow: Actual frame size from camera: {qimage.width()}x{qimage.height()}"
                )

        if (
            self._is_recording
            and self.trial_recorder
            and qimage
            and not qimage.isNull()
        ):
            try:
                numpy_frame = None
                if qimage.format() == QImage.Format_Grayscale8:
                    ptr = qimage.constBits()
                    if qimage.bytesPerLine() * qimage.height() == qimage.sizeInBytes():
                        numpy_frame = np.array(
                            ptr.asarray(qimage.sizeInBytes()), dtype=np.uint8
                        ).reshape(qimage.height(), qimage.width())
                    else:
                        log.warning(
                            "QImage (Grayscale8) has padding, converting line by line (slower)."
                        )
                        temp_image = qimage.convertToFormat(QImage.Format_Grayscale8)
                        ptr = temp_image.constBits()
                        # ptr.setsize(temp_image.sizeInBytes()) # Not needed if using asarray with size
                        numpy_frame = np.array(
                            ptr.asarray(temp_image.sizeInBytes()), dtype=np.uint8
                        ).reshape(temp_image.height(), temp_image.width())

                elif qimage.format() == QImage.Format_RGB888:
                    ptr = qimage.constBits()
                    if qimage.bytesPerLine() * qimage.height() == qimage.sizeInBytes():
                        numpy_frame = np.array(
                            ptr.asarray(qimage.sizeInBytes()), dtype=np.uint8
                        ).reshape(qimage.height(), qimage.width(), 3)
                    else:
                        log.warning(
                            "QImage (RGB888) has padding, converting line by line (slower)."
                        )
                        temp_image = qimage.convertToFormat(QImage.Format_RGB888)
                        ptr = temp_image.constBits()
                        # ptr.setsize(temp_image.sizeInBytes())
                        numpy_frame = np.array(
                            ptr.asarray(temp_image.sizeInBytes()), dtype=np.uint8
                        ).reshape(temp_image.height(), temp_image.width(), 3)

                if numpy_frame is not None:
                    self.trial_recorder.write_video_frame(numpy_frame.copy())
                else:
                    log.warning(
                        f"Unsupported QImage format for recording: {qimage.format()} or conversion failed. Cannot write video frame."
                    )

            except Exception as e:
                log.exception(
                    "MainWindow: Failed to write video frame during recording."
                )
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
        form_layout = QFormLayout(dialog)

        session_name_edit = QLineEdit(
            f"Session_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}"
        )
        form_layout.addRow("Session Name:", session_name_edit)
        operator_edit = QLineEdit()
        form_layout.addRow("Operator:", operator_edit)
        notes_edit = QTextEdit()
        notes_edit.setFixedHeight(80)
        form_layout.addRow("Notes:", notes_edit)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        form_layout.addRow(button_box)

        if dialog.exec_() != QDialog.Accepted:
            return

        session_name = (
            session_name_edit.text().strip() or session_name_edit.placeholderText()
        )

        safe_session_name = "".join(
            c if c.isalnum() or c in (" ", "_", "-") else "_" for c in session_name
        ).rstrip()
        safe_session_name = safe_session_name.replace(" ", "_")

        session_folder_path = os.path.join(PRIM_RESULTS_DIR, safe_session_name)
        try:
            os.makedirs(session_folder_path, exist_ok=True)
        except OSError as e:
            log.error(f"Failed to create session directory {session_folder_path}: {e}")
            QMessageBox.critical(
                self,
                "File System Error",
                f"Could not create directory:\n{session_folder_path}\n{e}",
            )
            return

        base_output_filename = os.path.join(session_folder_path, safe_session_name)
        self.last_trial_basepath = session_folder_path

        frame_w = self.current_camera_frame_width
        frame_h = self.current_camera_frame_height
        if frame_w <= 0 or frame_h <= 0:
            log.warning(
                f"Invalid frame size {frame_w}x{frame_h} for recording, falling back to DEFAULT_FRAME_SIZE"
            )
            frame_w, frame_h = DEFAULT_FRAME_SIZE

        video_ext_str_variant = self.video_format_combobox.currentData()
        # Ensure value() is called if it's a QVariant, otherwise use directly if it's already the string
        video_ext_str = (
            video_ext_str_variant.value()
            if isinstance(video_ext_str_variant, QVariant)
            else video_ext_str_variant
        )
        if not video_ext_str:
            video_ext_str = DEFAULT_VIDEO_EXTENSION.lower()  # Fallback

        video_codec_str = DEFAULT_VIDEO_CODEC

        log.info(
            f"Starting recording: Base='{base_output_filename}', FPS={DEFAULT_FPS}, Size={frame_w}x{frame_h}, Format={video_ext_str}"
        )

        try:
            self.trial_recorder = TrialRecorder(
                basepath=base_output_filename,
                fps=DEFAULT_FPS,
                frame_size=(frame_w, frame_h),
                video_ext=video_ext_str,
                video_codec=video_codec_str,
            )
            if not self.trial_recorder.is_recording:
                raise RuntimeError("TrialRecorder failed to initialize or start.")
        except Exception as e:
            log.exception("MainWindow: Failed to initialize TrialRecorder.")
            QMessageBox.critical(
                self, "Recording Error", f"Could not start recorder: {e}"
            )
            self.trial_recorder = None
            return

        self._is_recording = True
        self.start_recording_action.setIcon(self.icon_recording_active)
        self._update_recording_actions_enable_state()
        self.pressure_plot_widget.clear_plot()
        self.statusBar().showMessage(f"Recording Started: {session_name}", 0)

    def _trigger_stop_recording(self):
        if not self._is_recording:
            log.info("MainWindow: Stop recording called, but not currently recording.")
            return

        log.info("MainWindow: Stopping recording.")
        if self.trial_recorder:
            try:
                self.trial_recorder.stop()
                video_frames = self.trial_recorder.video_frame_count
                self.statusBar().showMessage(
                    f"Recording Stopped. Video Frames: {video_frames}", 7000
                )
                log.info(
                    f"Recording stopped successfully. Video frames written: {video_frames}"
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
                        try:
                            if sys.platform == "win32":
                                os.startfile(self.last_trial_basepath)
                            elif sys.platform == "darwin":
                                os.system(f'open "{self.last_trial_basepath}"')
                            else:
                                os.system(f'xdg-open "{self.last_trial_basepath}"')
                        except Exception as e_open:
                            log.error(
                                f"Could not open folder {self.last_trial_basepath}: {e_open}"
                            )

            except Exception as e:
                log.exception("MainWindow: Error during trial_recorder.stop().")
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
            QMessageBox.information(
                self, "No Plot Data", "There is no data in the plot to export."
            )
            return

        default_filename = (
            f"plot_data_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}.csv"
        )
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Plot Data as CSV",
            default_filename,
            "CSV Files (*.csv);;All Files (*)",
        )

        if not file_path:
            return

        try:
            with open(file_path, "w", newline="") as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(["time_s", "pressure_mmHg"])
                for t, p in zip(
                    self.pressure_plot_widget.times, self.pressure_plot_widget.pressures
                ):
                    writer.writerow([f"{t:.6f}", f"{p:.6f}"])
            self.statusBar().showMessage(
                f"Plot data exported to {os.path.basename(file_path)}", 4000
            )
        except Exception as e:
            log.exception(
                f"MainWindow: Failed to export plot data to CSV file: {file_path}"
            )
            QMessageBox.critical(
                self, "Export Error", f"Could not save plot data to CSV:\n{e}"
            )

    @pyqtSlot()
    def _show_about_dialog(self):
        QMessageBox.about(self, f"About {APP_NAME}", ABOUT_TEXT)

    def _update_app_session_time(self):
        self._app_session_seconds += 1
        hours = self._app_session_seconds // 3600
        minutes = (self._app_session_seconds % 3600) // 60
        seconds = self._app_session_seconds % 60
        self.app_session_time_label.setText(
            f"Session: {hours:02}:{minutes:02}:{seconds:02}"
        )

    def closeEvent(self, event):
        log.info(f"MainWindow: closeEvent received. Is recording: {self._is_recording}")
        if self._is_recording:
            reply = QMessageBox.question(
                self,
                "Confirm Exit",
                "Recording is currently in progress.\nDo you want to stop recording and exit?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self._trigger_stop_recording()
            else:
                event.ignore()
                return

        if self._serial_thread and self._serial_thread.isRunning():
            log.info("MainWindow: Stopping serial thread before exiting...")
            self._serial_thread.stop()
            if not self._serial_thread.wait(2000):
                log.warning(
                    "SerialThread did not stop gracefully on exit, terminating."
                )
                self._serial_thread.terminate()
                self._serial_thread.wait(500)
            self._serial_thread = None

        log.info("MainWindow: Calling close on QtCameraWidget.")
        self.qt_cam_widget.close()

        log.info(f"{APP_NAME} is shutting down.")
        super().closeEvent(event)
