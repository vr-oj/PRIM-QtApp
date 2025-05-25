# main_window.py
import os
import sys
import logging
import numpy as np
import csv
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QDockWidget,
    QTextEdit,
    QPushButton,
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
    QWidget,
    QSplitter,
    QSizePolicy,
    QMessageBox,
)
from PyQt5.QtCore import Qt, pyqtSlot, QTimer, QVariant, QDateTime, QSize, QThread
from PyQt5.QtGui import QIcon, QKeySequence, QImage

from prim_app import initialize_ic4_with_cti
from ui.control_panels.top_control_panel import TopControlPanel
from ui.canvas.pressure_plot_widget import PressurePlotWidget
from ui.canvas.gl_viewfinder import GLViewfinder
from camera.setup_wizard import CameraSetupWizard
from threads.serial_thread import SerialThread
from threads.sdk_camera_thread import SDKCameraThread
from recording import TrialRecorder, RecordingWorker
from utils.utils import list_serial_ports
from utils.config import (
    DEFAULT_FPS,
    DEFAULT_FRAME_SIZE,
    APP_NAME,
    APP_VERSION,
    PRIM_RESULTS_DIR,
    DEFAULT_VIDEO_EXTENSION,
    DEFAULT_VIDEO_CODEC,
    SUPPORTED_FORMATS,
    ABOUT_TEXT,
)

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._serial_thread = None
        self._recording_worker = None
        self._is_recording = False

        self._init_paths_and_icons()
        self._build_console_log_dock()
        self._build_central_widget_layout()
        self._build_menus()
        self._build_main_toolbar()
        self._build_status_bar()

        # Connect plot controls
        if hasattr(self, "top_ctrl") and hasattr(self, "pressure_plot_widget"):
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
        else:
            log.error("Plot controls not found for signal connections.")

        # Camera view setup (start thread after CTI via setup wizard)
        self.camera_view = GLViewfinder(self)
        self.main_splitter.insertWidget(1, self.camera_view)
        self.camera_thread = None  # Initialized in _run_camera_setup

        self.setWindowTitle(f"{APP_NAME} - v{APP_VERSION or '1.0'}")
        self.showMaximized()
        self.statusBar().showMessage("Ready. Select camera and serial port.", 5000)

        QTimer.singleShot(0, self._set_initial_splitter_sizes)
        self._set_initial_control_states()

    def _set_initial_splitter_sizes(self):
        # Get the total width of the splitter
        total = self.main_splitter.size().width()
        # You can tweak these ratios however you like
        left = int(total * 0.35)
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

        self.pressure_plot_widget = PressurePlotWidget(self)

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

        # Camera menu
        cam_menu = mb.addMenu("&Camera")
        setup_cam_act = QAction("Setup Camera…", self, triggered=self._run_camera_setup)
        cam_menu.addAction(setup_cam_act)

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

    def _run_camera_setup(self):
        wizard = CameraSetupWizard(self)
        if wizard.exec_() != QDialog.Accepted:
            return

        self.camera_settings = wizard.settings
        cti = self.camera_settings.get("ctiPath")
        try:
            initialize_ic4_with_cti(cti)
        except Exception as e:
            QMessageBox.critical(
                self, "Camera Setup Error", f"Failed to initialize camera SDK:\n{e}"
            )
            return

        # Teardown existing camera thread
        if self.camera_thread:
            self.camera_thread.stop()
            self.camera_thread = None

        # Launch new camera thread
        pattern = self.camera_settings.get("cameraSerialPattern")
        self.camera_thread = SDKCameraThread(device_name=pattern, fps=DEFAULT_FPS)
        self.camera_thread.frame_ready.connect(self.camera_view.update_frame)
        self.camera_thread.camera_error.connect(self._on_camera_error)
        # Optionally log mode/property updates
        self.camera_thread.resolutions_updated.connect(
            lambda lst: log.info(f"Camera resolutions: {lst}")
        )
        self.camera_thread.properties_updated.connect(
            lambda props: log.info(f"Camera properties: {props}")
        )
        self.camera_thread.start()

        self.statusBar().showMessage(
            f"Camera '{self.camera_settings.get('cameraModel')}' initialized", 5000
        )

    def _set_initial_control_states(self):
        self.top_ctrl.update_connection_status("Disconnected", False)
        self.start_recording_action.setEnabled(False)
        self.stop_recording_action.setEnabled(False)

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
        can_start_recording = serial_ready and not self._is_recording

        self.start_recording_action.setEnabled(bool(can_start_recording))
        self.stop_recording_action.setEnabled(bool(self._is_recording))

    def _trigger_start_recording_dialog(self):
        if not (self._serial_thread and self._serial_thread.isRunning()):
            QMessageBox.warning(
                self, "Cannot Start Recording", "PRIM device not connected."
            )
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
        operator_edit = (
            QLineEdit()
        )  # This data is collected but not used in current snippet
        layout.addRow("Operator:", operator_edit)
        notes_edit = (
            QTextEdit()
        )  # This data is collected but not used in current snippet
        notes_edit.setFixedHeight(80)
        layout.addRow("Notes:", notes_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return

        session_name_raw = name_edit.text().strip() or name_edit.placeholderText()
        session_name_safe = (
            "".join(
                c if c.isalnum() or c in (" ", "_", "-") else "_"
                for c in session_name_raw
            )
            .rstrip()
            .replace(" ", "_")
        )

        session_folder = os.path.join(PRIM_RESULTS_DIR, session_name_safe)
        try:
            os.makedirs(session_folder, exist_ok=True)
        except Exception as e:
            log.error(f"Couldn’t create folder {session_folder}: {e}")
            QMessageBox.critical(self, "File Error", str(e))
            return

        # This is the base path for TrialRecorder (e.g., "PRIM_RESULTS_DIR/Session_XYZ/Session_XYZ")
        # TrialRecorder will append its own timestamp and extensions like "_20230101-120000.csv"
        recording_base_prefix = os.path.join(session_folder, session_name_safe)

        # self.last_trial_basepath is used to open the folder later in _trigger_stop_recording
        self.last_trial_basepath = session_folder

        # Use fallback frame size and default video parameters from config.py
        w, h = DEFAULT_FRAME_SIZE
        video_ext = DEFAULT_VIDEO_EXTENSION.lower()
        codec = DEFAULT_VIDEO_CODEC

        log.info(
            f"Attempting to start recording session: '{session_name_safe}' in folder '{session_folder}'"
        )
        log.info(
            f"Parameters for RecordingWorker/TrialRecorder: "
            f"FPS: {DEFAULT_FPS}, FrameSize: {w}x{h}, VideoFormat: {video_ext}, Codec: {codec}"
        )

        try:
            if self._recording_worker and self._recording_worker.isRunning():
                log.warning("A recording worker is already running. Stopping it first.")
                self._recording_worker.stop_worker()
                if not self._recording_worker.wait(3000):
                    log.warning(
                        "Recording worker did not stop gracefully, terminating."
                    )
                    self._recording_worker.terminate()
                self._recording_worker.deleteLater()
                self._recording_worker = None

            # Initialize the RecordingWorker correctly
            self._recording_worker = RecordingWorker(
                basepath=recording_base_prefix,
                fps=DEFAULT_FPS,
                frame_size=(w, h),
                video_ext=video_ext,
                video_codec=codec,
                parent=self,  # Pass parent for QObject hierarchy if RecordingWorker is a QObject
            )

            self._recording_worker.start()  # Start the worker thread

            # Wait briefly for the worker's internal TrialRecorder to initialize.
            # A signal from RecordingWorker upon successful TrialRecorder init would be more robust.
            QThread.msleep(200)  # milliseconds

            if not (
                self._recording_worker
                and self._recording_worker.isRunning()
                and self._recording_worker.is_ready_to_record  # Crucial check
            ):
                log.error(
                    "Recording worker did not become ready. Check RecordingWorker logs for "
                    "initialization errors in TrialRecorder (e.g., file access, codec issues)."
                )
                if self._recording_worker:  # If instance exists but not ready
                    if self._recording_worker.isRunning():
                        self._recording_worker.stop_worker()
                        if not self._recording_worker.wait(1000):
                            self._recording_worker.terminate()
                    self._recording_worker.deleteLater()
                    self._recording_worker = None
                raise RuntimeError(
                    "Recording worker failed to initialize TrialRecorder or did not start."
                )

        except Exception as e:
            log.exception(f"Failed to initialize or start RecordingWorker: {e}")
            QMessageBox.critical(
                self, "Recording Error", f"Could not start recording worker: {e}"
            )
            # Ensure cleanup if instance was created but an error occurred
            if self._recording_worker:
                if self._recording_worker.isRunning():
                    self._recording_worker.stop_worker()
                    if not self._recording_worker.wait(1000):  # Brief wait
                        self._recording_worker.terminate()
                self._recording_worker.deleteLater()
                self._recording_worker = None
            return

        # If we reach here, worker started and is ready
        self._is_recording = True
        self.start_recording_action.setIcon(self.icon_recording_active)  # Update UI
        self._update_recording_actions_enable_state()
        self.pressure_plot_widget.clear_plot()  # Clear plot for new recording
        self.statusBar().showMessage(f"Recording Started: {session_name_safe}", 0)

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

            # ─── Export complete plot data to CSV ────────────────────────────
            try:
                import csv, os

                csv_path = os.path.join(self.last_trial_basepath, "plot_data.csv")
                with open(csv_path, "w", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(["time_s", "pressure_mmHg"])
                    for t, p in zip(
                        self.pressure_plot_widget.times,
                        self.pressure_plot_widget.pressures,
                    ):
                        writer.writerow([f"{t:.6f}", f"{p:.6f}"])
                self.statusBar().showMessage(
                    f"Plot CSV saved to {os.path.basename(csv_path)}", 5000
                )
            except Exception as e:
                log.exception(f"Failed to save plot CSV: {e}")
                QMessageBox.warning(
                    self, "CSV Export Error", f"Could not save plot CSV: {e}"
                )

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

    @pyqtSlot(str, str)
    def _on_camera_error(self, msg, code):
        QMessageBox.critical(self, "Camera Error", f"{msg}\n(Code: {code})")

    def closeEvent(self, event):
        # Prompt if recording
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
                QApplication.processEvents()
            else:
                event.ignore()
                return

        # Cleanup recording worker
        if self._recording_worker:
            self._recording_worker.stop_worker()
            self._recording_worker.wait(3000)
            self._recording_worker.deleteLater()
            self._recording_worker = None

        # Cleanup serial thread
        if self._serial_thread and self._serial_thread.isRunning():
            self._serial_thread.stop()
            self._serial_thread.wait(2000)
            self._serial_thread.deleteLater()
            self._serial_thread = None

        # Cleanup camera thread
        if self.camera_thread:
            self.camera_thread.stop()
            self.camera_thread = None

        super().closeEvent(event)
