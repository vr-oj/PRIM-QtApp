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
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if base_dir not in sys.path:
        sys.path.insert(0, base_dir)
    import prim_app

    _IC4_AVAILABLE = getattr(prim_app, "IC4_AVAILABLE", False)
    _IC4_INITIALIZED = getattr(prim_app, "IC4_INITIALIZED", False)
    if _IC4_INITIALIZED:
        import imagingcontrol4 as ic4_sdk

        _ic4_module = ic4_sdk
    logging.getLogger(__name__).info(
        "IC4 flags: AVAILABLE=%s INITIALIZED=%s",
        _IC4_AVAILABLE,
        _IC4_INITIALIZED,
    )
except Exception as e:
    logging.getLogger(__name__).warning(f"IC4 check failed: {e}")

from threads.qtcamera_widget import QtCameraWidget
from threads.serial_thread import SerialThread
from recording import TrialRecorder, RecordingWorker
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
        self._recording_worker = None
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

        # set up your initial splitter sizes (e.g. 2/3 : 1/3)
        QTimer.singleShot(0, self._set_initial_splitter_sizes)

        self._set_initial_control_states()
        self._connect_top_control_panel_signals()
        self._connect_camera_widget_signals()

        # Populate camera list after a short delay
        if hasattr(self.top_ctrl, "camera_controls") and self.top_ctrl.camera_controls:
            QTimer.singleShot(250, self.top_ctrl.camera_controls.populate_camera_list)

    def _set_initial_splitter_sizes(self):
        # Get the total width of the splitter
        total = self.main_splitter.size().width()
        # You can tweak these ratios however you like
        left = int(total * 0.60)
        right = total - left
        self.main_splitter.setSizes([left, right])

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
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(2, 2, 2, 2)
        outer.setSpacing(3)

        self.top_ctrl = TopControlPanel(self)
        self.top_ctrl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        outer.addWidget(self.top_ctrl)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)

        self.qt_cam_widget = QtCameraWidget(self)
        self.pressure_plot_widget = PressurePlotWidget(self)

        self.main_splitter.addWidget(self.qt_cam_widget)
        self.main_splitter.addWidget(self.pressure_plot_widget)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 0)

        outer.addWidget(self.main_splitter, 1)
        self.setCentralWidget(central)

    def _build_menus(self):
        mb = self.menuBar()
        # --- File Menu ---
        fm = mb.addMenu("&File")
        exp_data = QAction("Export Plot &Data (CSV)…", self)
        exp_data.triggered.connect(self._export_plot_data_as_csv)
        fm.addAction(exp_data)

        exp_img = QAction("Export Plot &Image…", self)
        exp_img.triggered.connect(self.pressure_plot_widget.export_as_image)
        fm.addAction(exp_img)
        fm.addSeparator()
        exit_act = QAction("&Exit", self, shortcut=QKeySequence.Quit)
        exit_act.triggered.connect(self.close)
        fm.addAction(exit_act)

        # --- Acquisition ---
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

        # --- View ---
        vm = mb.addMenu("&View")
        vm.addAction(self.dock_console.toggleViewAction())

        # --- Plot ---
        pm = mb.addMenu("&Plot")
        clear_plot = QAction(
            "&Clear Plot Data", self, triggered=self._clear_pressure_plot
        )
        pm.addAction(clear_plot)
        reset_zoom = QAction(
            "&Reset Plot Zoom",
            self,
            triggered=lambda: self.pressure_plot_widget.reset_zoom(
                self.top_ctrl.plot_controls.auto_x_cb.isChecked(),
                self.top_ctrl.plot_controls.auto_y_cb.isChecked(),
            ),
        )
        pm.addAction(reset_zoom)

        # --- Help ---
        hm = mb.addMenu("&Help")
        about = QAction(f"&About {APP_NAME}", self, triggered=self._show_about_dialog)
        hm.addAction(about)
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
        self.serial_port_combobox.setToolTip("Select Serial Port for PRIM device")
        self.serial_port_combobox.setMinimumWidth(200)
        self.serial_port_combobox.addItem("🔌 Simulated Data", QVariant())
        ports = list_serial_ports()
        if ports:
            for p, d in ports:
                self.serial_port_combobox.addItem(
                    f"{os.path.basename(p)} ({d})", QVariant(p)
                )
        else:
            self.serial_port_combobox.addItem("No Serial Ports Found", QVariant())
            self.serial_port_combobox.setEnabled(False)
        tb.addWidget(self.serial_port_combobox)

        self.video_format_combobox = QComboBox()
        self.video_format_combobox.setToolTip("Select Video Recording Format")
        for fmt in SUPPORTED_FORMATS:
            self.video_format_combobox.addItem(fmt.upper(), QVariant(fmt))
        default_idx = self.video_format_combobox.findData(
            QVariant(DEFAULT_VIDEO_EXTENSION.lower())
        )
        if default_idx != -1:
            self.video_format_combobox.setCurrentIndex(default_idx)
        tb.addWidget(self.video_format_combobox)

        tb.addSeparator()
        tb.addAction(self.start_recording_action)
        tb.addAction(self.stop_recording_action)

    def _build_status_bar(self):
        sb = self.statusBar() or QStatusBar(self)
        self.setStatusBar(sb)

        self.app_session_time_label = QLabel("Session: 00:00:00")
        sb.addPermanentWidget(self.app_session_time_label)
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
        tc.exposure_changed.connect(self.qt_cam_widget.set_exposure)
        tc.gain_changed.connect(self.qt_cam_widget.set_gain)
        tc.auto_exposure_toggled.connect(self.qt_cam_widget.set_auto_exposure)

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
        # Safely only hook up if that slot actually exists
        if (
            hasattr(self.top_ctrl, "camera_controls")
            and self.top_ctrl.camera_controls
            and hasattr(self.top_ctrl.camera_controls, "update_camera_resolutions_list")
        ):
            self.qt_cam_widget.camera_resolutions_updated.connect(
                self.top_ctrl.camera_controls.update_camera_resolutions_list
            )

        if (
            hasattr(self.top_ctrl, "camera_controls")
            and self.top_ctrl.camera_controls
            and hasattr(self.top_ctrl.camera_controls, "update_camera_properties_ui")
        ):
            self.qt_cam_widget.camera_properties_updated.connect(
                self.top_ctrl.camera_controls.update_camera_properties_ui
            )

        self.qt_cam_widget.camera_error.connect(self._handle_camera_error)
        self.qt_cam_widget.frame_ready.connect(self._handle_new_camera_frame)

    @pyqtSlot(object)
    def _handle_camera_selection(self, device_info_obj):
        log.debug(
            f"MainWindow: Camera selection changed. DeviceInfo type: {type(device_info_obj)}"
        )

        is_ic4_device = False
        if (
            _IC4_INITIALIZED
            and _ic4_module
            and isinstance(device_info_obj, _ic4_module.DeviceInfo)
        ):
            is_ic4_device = True
            log.info(
                f"Selected TIS Camera: {device_info_obj.model_name if device_info_obj else 'None'}"
            )
        elif device_info_obj is not None:
            log.warning(
                f"Selected camera is not a TIS DeviceInfo object. Type: {type(device_info_obj)}"
            )

        if is_ic4_device:
            self.qt_cam_widget.set_active_camera_device(device_info_obj)
        else:
            self.qt_cam_widget.set_active_camera_device(
                None
            )  # Handles None or non-IC4 objects
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
            self._serial_thread.stop()  # stop() will emit finished when done
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
                # Ensure any previous thread instance is fully cleaned up if it exists
                # This is more for robustness, stop() should handle it.
                if self._serial_thread:
                    if (
                        self._serial_thread.isRunning()
                    ):  # Should not happen if logic is correct
                        log.warning(
                            "Previous serial thread was still running, attempting to stop it forcefully."
                        )
                        self._serial_thread.stop()
                        if not self._serial_thread.wait(1000):
                            self._serial_thread.terminate()
                            self._serial_thread.wait(500)
                    self._serial_thread.deleteLater()  # Schedule for deletion
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
                if self._serial_thread:  # If instance was created but start failed
                    self._serial_thread.deleteLater()
                self._serial_thread = None
                self._update_recording_actions_enable_state()  # Reflect failed connection attempt

    @pyqtSlot(str)
    def _handle_serial_status_change(self, status: str):
        log.info(f"Serial status: {status}")
        self.statusBar().showMessage(f"PRIM Device: {status}", 4000)

        # More robust check for "connected" state
        connected = (
            "connected" in status.lower() or "opened serial port" in status.lower()
        )

        self.top_ctrl.update_connection_status(status, connected)
        if connected:
            self.connect_serial_action.setIcon(self.icon_disconnect)
            self.connect_serial_action.setText("Disconnect PRIM Device")
            self.serial_port_combobox.setEnabled(False)
            self.pressure_plot_widget.clear_plot()  # Clear plot on new connection
        else:  # Disconnected or error states
            self.connect_serial_action.setIcon(self.icon_connect)
            self.connect_serial_action.setText("Connect PRIM Device")
            self.serial_port_combobox.setEnabled(True)
            if self._is_recording:  # If was recording and device disconnected
                QMessageBox.information(
                    self,
                    "Recording Stopped",
                    "PRIM device disconnected during recording.",
                )
                self._trigger_stop_recording()  # Stop the recording
        self._update_recording_actions_enable_state()

    @pyqtSlot(str)
    def _handle_serial_error(self, msg: str):
        log.error(f"Serial error: {msg}")
        self.statusBar().showMessage(f"Serial Error: {msg}", 6000)
        # UI should already be updated by status_changed if connection failed
        # self._handle_serial_status_change(f"Error: {msg}") # This might cause loop if error leads to disconnect status
        self._update_recording_actions_enable_state()

    @pyqtSlot()
    def _handle_serial_thread_finished(self):
        log.info("SerialThread finished signal received.")
        # Check if the sender is indeed our current serial thread
        sender_thread = self.sender()
        if self._serial_thread is sender_thread:
            # Update UI to reflect disconnected state if it wasn't already
            # This handles cases where thread stops without an explicit "Disconnected" status emitted
            # (e.g., if stop() is called directly)
            current_status_text = (
                self.top_ctrl.conn_lbl.text().lower()
                if hasattr(self.top_ctrl, "conn_lbl")
                else ""
            )
            is_ui_connected = (
                "connected" in current_status_text
                or "opened serial port" in current_status_text
            )

            if is_ui_connected:  # If UI still shows connected, update it
                self._handle_serial_status_change("Disconnected by thread finishing")

            if self._serial_thread:  # Ensure it exists before deleteLater
                self._serial_thread.deleteLater()  # Schedule for deletion
            self._serial_thread = None
            log.info("SerialThread instance cleaned up.")
        else:
            log.warning(
                "Received 'finished' signal from an old or unknown SerialThread instance."
            )

        self._update_recording_actions_enable_state()

    @pyqtSlot(int, float, float)
    def _handle_new_serial_data(self, idx: int, t: float, p: float):
        self.top_ctrl.update_prim_data(idx, t, p)
        ax = self.top_ctrl.plot_controls.auto_x_cb.isChecked()
        ay = self.top_ctrl.plot_controls.auto_y_cb.isChecked()
        self.pressure_plot_widget.update_plot(t, p, ax, ay)
        if self.dock_console.isVisible():
            self.console_out_textedit.append(
                f"PRIM Data: Idx={idx}, Time={t:.3f}s, P={p:.2f}"
            )

        if self._is_recording and self._recording_worker:
            try:
                self._recording_worker.add_csv_data(t, idx, p)
            except Exception:
                log.exception("Error queueing CSV data for recording.")
                self.statusBar().showMessage(
                    "CSV queue error. Stopping recording.", 5000
                )
                self._trigger_stop_recording()

    def _update_recording_actions_enable_state(self):
        serial_ready = (
            self._serial_thread is not None and self._serial_thread.isRunning()
        )
        camera_ready = self.qt_cam_widget.current_camera_is_active()
        can_start_recording = serial_ready and camera_ready and not self._is_recording

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

        if self._is_recording and self._recording_worker and not qimage.isNull():
            try:
                numpy_frame = None
                if qimage.format() == QImage.Format_Grayscale8:
                    ptr = qimage.constBits()
                    ptr.setsize(qimage.sizeInBytes())  # Important for PySide/PyQt5
                    numpy_frame = np.array(ptr, dtype=np.uint8).reshape(
                        qimage.height(), qimage.width()
                    )
                elif (
                    qimage.format() == QImage.Format_RGB888
                ):  # Assuming RGB888 is 3 channels
                    ptr = qimage.constBits()
                    ptr.setsize(qimage.sizeInBytes())
                    numpy_frame = np.array(ptr, dtype=np.uint8).reshape(
                        qimage.height(), qimage.width(), 3
                    )
                # Add other formats if necessary, e.g. Format_RGB32 (BGRA typically)
                # elif qimage.format() == QImage.Format_RGB32:
                #     ptr = qimage.constBits()
                #     ptr.setsize(qimage.sizeInBytes())
                #     numpy_frame = np.array(ptr, dtype=np.uint8).reshape(
                #         qimage.height(), qimage.width(), 4
                #     ) # BGRA
                #     # numpy_frame = numpy_frame[..., :3] # If you need to convert to RGB

                if numpy_frame is not None:
                    self._recording_worker.add_video_frame(
                        numpy_frame.copy()
                    )  # Send copy
                else:
                    # Corrected: Log warning if numpy_frame is None (format not handled)
                    log.warning(
                        f"Unsupported QImage format ({qimage.format()}) for video frame, not sending to recorder."
                    )

            except Exception as e:  # Catch specific errors if possible
                log.exception(
                    f"Error converting QImage to numpy or queueing video frame: {e}"
                )
                self.statusBar().showMessage(
                    "Video frame error. Stopping recording.", 5000
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
            log.warning(
                f"Invalid frame size ({w}x{h}), using default {DEFAULT_FRAME_SIZE}."
            )
            w, h = DEFAULT_FRAME_SIZE

        ext_data = self.video_format_combobox.currentData()
        video_ext = ext_data.value() if isinstance(ext_data, QVariant) else ext_data
        if not video_ext:
            video_ext = DEFAULT_VIDEO_EXTENSION.lower()
        codec = DEFAULT_VIDEO_CODEC

        log.info(
            f"Attempting to start recording: {base}, {DEFAULT_FPS} FPS, {w}x{h}, format: {video_ext}, codec: {codec}"
        )
        try:
            if self._recording_worker and self._recording_worker.isRunning():
                log.warning("A recording worker is already running. Stopping it first.")
                self._recording_worker.stop_worker()
                if not self._recording_worker.wait(3000):
                    self._recording_worker.terminate()
                self._recording_worker.deleteLater()
                self._recording_worker = None

            self._recording_worker = RecordingWorker(
                basepath=base,
                fps=DEFAULT_FPS,
                frame_size=(w, h),
                video_ext=video_ext,
                video_codec=codec,
                parent=self,
            )

            # CRITICAL: Start the thread so its run() method executes
            self._recording_worker.start()

            # The sleep is a temporary, imperfect way to wait for initialization.
            # A signal from RecordingWorker would be much better.
            # Increase sleep slightly to give more time for file I/O in TrialRecorder init.
            time.sleep(0.5)  # Increased from 0.2, still not ideal.

            if not (
                self._recording_worker
                and self._recording_worker.isRunning()
                and self._recording_worker.is_ready_to_record
            ):
                # If worker is not running or not ready, it means init failed.
                # The RecordingWorker's run() method should have logged the specific error.
                log.error(
                    "Recording worker did not become ready. Check RecordingWorker logs for initialization errors in TrialRecorder."
                )
                # Attempt to clean up the worker if it was created but isn't ready
                if self._recording_worker:
                    if self._recording_worker.isRunning():
                        self._recording_worker.stop_worker()  # Signal it to stop if it's in its loop
                        if not self._recording_worker.wait(1000):  # Brief wait
                            self._recording_worker.terminate()
                    self._recording_worker.deleteLater()
                    self._recording_worker = None
                raise RuntimeError(  # This error will be caught by the outer try-except
                    "Recording worker failed to initialize TrialRecorder or did not start."
                )

        except Exception as e:
            log.exception(
                f"Failed to initialize or start RecordingWorker: {e}"
            )  # This catches the RuntimeError above too
            QMessageBox.critical(
                self, "Recording Error", f"Could not start recording worker: {e}"
            )
            if self._recording_worker:  # Ensure cleanup if instance was created
                if self._recording_worker.isRunning():
                    self._recording_worker.stop_worker()
                    if not self._recording_worker.wait(1000):
                        self._recording_worker.terminate()
                self._recording_worker.deleteLater()
            self._recording_worker = None
            return  # Do not proceed to set _is_recording = True

        # If we reach here, worker started and is ready
        self._is_recording = True
        self.start_recording_action.setIcon(self.icon_recording_active)
        self._update_recording_actions_enable_state()
        self.pressure_plot_widget.clear_plot()
        self.statusBar().showMessage(f"Recording Started: {safe}", 0)

    def _trigger_stop_recording(self):
        if not self._is_recording or not self._recording_worker:
            log.info("Stop recording triggered, but not recording or worker missing.")
            # Ensure UI consistency if state is desynced
            if self._is_recording:  # If flag is true but worker is missing
                self._is_recording = False
            self._update_recording_actions_enable_state()
            return

        log.info("Stopping recording worker...")
        try:
            self._recording_worker.stop_worker()  # Signal the worker to stop

            # Wait for the worker thread to finish its queue and exit
            # Increased timeout as file closing can take time
            if not self._recording_worker.wait(7000):
                log.warning(
                    "Recording worker did not stop gracefully after 7s. Terminating."
                )
                self._recording_worker.terminate()  # Force if necessary
                # If terminated, frame count might not be perfectly up-to-date
                # but it's better than hanging.

            count = self._recording_worker.video_frame_count
            self.statusBar().showMessage(
                f"Recording Stopped. {count} frames saved.", 7000
            )

            reply = QMessageBox.information(
                self,
                "Recording Saved",
                f"Session saved to:\n{self.last_trial_basepath}\n\nOpen folder?",
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

        except Exception as e:  # Catch any unexpected errors during stop process
            log.exception(f"Error during the stop recording process: {e}")
            self.statusBar().showMessage("Error stopping recording.", 5000)
        finally:
            # Ensure worker is cleaned up
            if self._recording_worker:
                if (
                    self._recording_worker.isRunning()
                ):  # Should be false if wait() succeeded
                    log.warning(
                        "Recording worker still running in finally block of stop. Forcing stop."
                    )
                    self._recording_worker.stop_worker()  # Resend stop just in case
                    if not self._recording_worker.wait(1000):
                        self._recording_worker.terminate()
                self._recording_worker.deleteLater()  # Schedule for deletion
            self._recording_worker = None

            # Reset recording state
            self._is_recording = False
            self.start_recording_action.setIcon(self.icon_record_start)
            self._update_recording_actions_enable_state()
            log.info("Recording fully stopped and UI updated.")

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
        except Exception as e:
            log.exception(f"Failed to export plot data: {e}")
            QMessageBox.critical(self, "Export Error", f"Could not save CSV: {e}")

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
        log.info(f"Close event received. Recording active: {self._is_recording}")
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
                # _trigger_stop_recording now handles waiting for the worker.
                # Allow a brief moment for UI events related to stopping.
                QApplication.processEvents()
            else:
                event.ignore()
                return

        # Ensure recording worker is stopped and cleaned up if it still exists
        # (e.g., if recording was not active but worker was somehow created and not cleaned)
        if self._recording_worker:
            log.info("Cleaning up recording worker on application exit...")
            if self._recording_worker.isRunning():
                self._recording_worker.stop_worker()
                if not self._recording_worker.wait(3000):
                    log.warning(
                        "Recording worker did not stop gracefully on exit, terminating."
                    )
                    self._recording_worker.terminate()
            self._recording_worker.deleteLater()
            self._recording_worker = None

        # Stop Serial Thread
        if self._serial_thread and self._serial_thread.isRunning():
            log.info("Stopping serial thread on application exit...")
            self._serial_thread.stop()
            if not self._serial_thread.wait(2000):
                log.warning(
                    "Serial thread did not stop gracefully on exit, terminating."
                )
                self._serial_thread.terminate()
                if not self._serial_thread.wait(500):  # Wait after terminate
                    log.error("Serial thread failed to terminate.")
            self._serial_thread.deleteLater()
            self._serial_thread = None

        log.info("Closing camera widget.")
        if self.qt_cam_widget:  # Check if it exists
            self.qt_cam_widget.close()  # This should trigger its own cleanup

        log.info("Exiting application.")
        super().closeEvent(event)
