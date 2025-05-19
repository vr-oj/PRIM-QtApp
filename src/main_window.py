import os
import csv
import logging
import numpy as np  # For QImage to NumPy array conversion

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
    QVariant,  # For QComboBox data
)
from PyQt5.QtGui import (
    QIcon,
    QKeySequence,
    QImage,
)  # QImage for frame_ready signal type hint

# Conditional import of imagingcontrol4 types if SDK is available
try:
    from prim_app import IC4_AVAILABLE, IC4_INITIALIZED

    if IC4_INITIALIZED:  # Only import if SDK initialized successfully
        import imagingcontrol4 as ic4  # For type hinting ic4.DeviceInfo
    else:
        ic4 = None  # ic4 won't be used if not initialized
except ImportError:
    IC4_AVAILABLE = False
    IC4_INITIALIZED = False
    ic4 = None


from threads.qtcamera_widget import QtCameraWidget
from threads.serial_thread import SerialThread
from recording import (
    TrialRecorder,
)  # Ensure this handles numpy arrays or can be adapted
from utils import list_serial_ports

# Control Panels
from control_panels.top_control_panel import TopControlPanel

# No direct import of CameraControlPanel/PlotControlPanel needed if TopControlPanel handles them

from canvas.pressure_plot_widget import PressurePlotWidget

from config import (
    APP_NAME,
    APP_VERSION,
    ABOUT_TEXT,
    # LOG_LEVEL, # LOG_LEVEL is used in prim_app.py
    DEFAULT_FPS,
    DEFAULT_FRAME_SIZE,
    # DEFAULT_CAMERA_INDEX, # Less relevant for TIS SDK
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
        self.last_trial_basepath = ""  # Store the folder of the last trial

        self.current_camera_frame_width = DEFAULT_FRAME_SIZE[0]
        self.current_camera_frame_height = DEFAULT_FRAME_SIZE[1]
        self.current_camera_pixel_format_str = "Mono 8"  # Default assumption

        self._init_paths_and_icons()
        self._build_console_log_dock()  # Renamed for clarity
        self._build_central_widget_layout()  # Renamed for clarity
        self._build_menus()  # Renamed for clarity
        self._build_main_toolbar()  # Renamed for clarity
        self._build_status_bar()  # Renamed for clarity

        self.setWindowTitle(f"{APP_NAME} - v{APP_VERSION}")
        self.showMaximized()
        # QTimer.singleShot(300, self._adjust_splitter_sizes) # Renamed, if still needed
        self.statusBar().showMessage(
            "Ready. Select camera (if available) and serial port.", 5000
        )

        self._set_initial_control_states()  # Renamed
        self._connect_top_control_panel_signals()  # Renamed
        self._connect_camera_widget_signals()

        # Populate camera list once UI is up and SDK might be initialized
        # The TopControlPanel now has CameraControlPanel, which populates its own list.
        # If CameraControlPanel.populate_camera_list needs to be triggered after main window shows:
        QTimer.singleShot(200, self.top_ctrl.camera_controls.populate_camera_list)

    def _init_paths_and_icons(self):
        base = os.path.dirname(os.path.abspath(__file__))  # More robust base path
        icon_dir = os.path.join(base, "icons")

        def get_icon(name):
            path = os.path.join(icon_dir, name)
            if not os.path.exists(path):
                log.warning(f"Icon not found: {path}")
                return QIcon()  # Return empty icon
            return QIcon(path)

        self.icon_record_start = get_icon("record.svg")
        self.icon_record_stop = get_icon("stop.svg")
        self.icon_recording_active = get_icon(
            "recording_active.svg"
        )  # Assuming this exists
        self.icon_connect = get_icon("plug.svg")
        self.icon_disconnect = get_icon("plug_disconnect.svg")  # Assuming this exists

    def _build_console_log_dock(self):
        self.dock_console = QDockWidget("Console Log", self)
        self.dock_console.setObjectName("ConsoleLogDock")  # For saving/restoring state
        self.dock_console.setAllowedAreas(
            Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea
        )

        console_widget = QWidget()  # Use a QWidget as container for layout
        layout = QVBoxLayout(console_widget)
        self.console_out_textedit = QTextEdit(readOnly=True)  # Renamed for clarity
        self.console_out_textedit.setFontFamily(
            "monospace"
        )  # Optional: for better log readability
        layout.addWidget(self.console_out_textedit)
        self.dock_console.setWidget(console_widget)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.dock_console)
        self.dock_console.setVisible(False)  # Start hidden

    def _build_central_widget_layout(self):
        central_container_widget = QWidget()  # Main container for central area
        outer_layout = QVBoxLayout(central_container_widget)
        outer_layout.setContentsMargins(2, 2, 2, 2)
        outer_layout.setSpacing(3)

        # Top Control Panel (contains camera and plot controls)
        self.top_ctrl = TopControlPanel(self)
        self.top_ctrl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        outer_layout.addWidget(self.top_ctrl)

        # Main Splitter for Camera View and Plot
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)

        self.qt_cam_widget = QtCameraWidget(self)  # Renamed for clarity
        self.pressure_plot_widget = PressurePlotWidget(self)  # Renamed for clarity

        self.main_splitter.addWidget(self.qt_cam_widget)
        self.main_splitter.addWidget(self.pressure_plot_widget)
        self.main_splitter.setStretchFactor(0, 2)  # Camera view gets 2 parts of stretch
        self.main_splitter.setStretchFactor(1, 3)  # Plot gets 3 parts

        outer_layout.addWidget(self.main_splitter, 1)  # Give splitter expanding space
        self.setCentralWidget(central_container_widget)

    def _build_menus(self):
        menubar = self.menuBar()  # Simpler var name

        # File Menu
        file_menu = menubar.addMenu("&File")
        export_plot_data_action = QAction("Export Plot &Data (CSV)…", self)
        export_plot_data_action.triggered.connect(
            self._export_plot_data_as_csv
        )  # Renamed slot
        file_menu.addAction(export_plot_data_action)

        export_plot_image_action = QAction("Export Plot &Image…", self)
        export_plot_image_action.triggered.connect(
            self.pressure_plot_widget.export_as_image
        )
        file_menu.addAction(export_plot_image_action)
        file_menu.addSeparator()
        exit_action = QAction("&Exit", self, shortcut=QKeySequence.Quit)
        exit_action.triggered.connect(
            self.close
        )  # Qt's close() method, which calls closeEvent
        file_menu.addAction(exit_action)

        # Acquisition Menu
        acq_menu = menubar.addMenu("&Acquisition")
        self.start_recording_action = QAction(
            self.icon_record_start,
            "Start &Recording",
            self,
            shortcut=Qt.CTRL | Qt.Key_R,
            triggered=self._trigger_start_recording_dialog,  # Renamed slot
            enabled=False,  # Enabled when serial and camera are ready
        )
        acq_menu.addAction(self.start_recording_action)

        self.stop_recording_action = QAction(
            self.icon_record_stop,
            "Stop R&ecording",
            self,
            shortcut=Qt.CTRL | Qt.Key_T,  # Changed shortcut to avoid conflict if any
            triggered=self._trigger_stop_recording,  # Renamed slot
            enabled=False,
        )
        acq_menu.addAction(self.stop_recording_action)

        # View Menu
        view_menu = menubar.addMenu("&View")
        view_menu.addAction(
            self.dock_console.toggleViewAction()
        )  # Toggle console log visibility

        # Plot Menu
        plot_menu = menubar.addMenu("&Plot")
        clear_plot_action = QAction(
            "&Clear Plot Data", self, triggered=self._clear_pressure_plot
        )  # Renamed slot
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

        # Help Menu
        help_menu = menubar.addMenu("&Help")
        about_app_action = QAction(
            f"&About {APP_NAME}", self, triggered=self._show_about_dialog
        )  # Renamed slot
        help_menu.addAction(about_app_action)
        help_menu.addAction("About &Qt", QApplication.instance().aboutQt)

    def _build_main_toolbar(self):
        toolbar = QToolBar("Main Controls")
        toolbar.setObjectName("MainControlsToolbar")
        toolbar.setIconSize(QSize(20, 20))  # Standard icon size
        toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        self.connect_serial_action = QAction(
            self.icon_connect,
            "&Connect PRIM Device",
            self,
            triggered=self._toggle_serial_connection,  # Renamed slot
        )
        toolbar.addAction(self.connect_serial_action)

        self.serial_port_combobox = QComboBox()
        self.serial_port_combobox.setToolTip("Select Serial Port for PRIM device")
        self.serial_port_combobox.setMinimumWidth(200)  # Give it some space
        self.serial_port_combobox.addItem(
            "🔌 Simulated Data", QVariant()
        )  # Default option with None data
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
        for fmt_str in SUPPORTED_FORMATS:  # From config.py
            self.video_format_combobox.addItem(fmt_str.upper(), QVariant(fmt_str))
        # Set default format if specified in config
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
        status_bar = self.statusBar() or QStatusBar(self)  # Ensure status bar exists
        self.setStatusBar(status_bar)

        self.app_session_time_label = QLabel("Session: 00:00:00")
        status_bar.addPermanentWidget(self.app_session_time_label)
        self._app_session_seconds = 0
        self._app_session_timer = QTimer(self, interval=1000)  # Timer per second
        self._app_session_timer.timeout.connect(self._update_app_session_time)
        self._app_session_timer.start()

    def _set_initial_control_states(self):
        self.top_ctrl.update_connection_status("Disconnected", False)
        self.top_ctrl.camera_controls.disable_all_controls()  # Access CameraControlPanel via TopControlPanel
        self.start_recording_action.setEnabled(False)
        self.stop_recording_action.setEnabled(False)

    def _connect_top_control_panel_signals(self):
        tc = self.top_ctrl  # Alias for TopControlPanel

        # Camera related signals from TopControlPanel (which forwards from CameraControlPanel)
        tc.camera_selected.connect(self._handle_camera_selection)
        tc.resolution_selected.connect(self._handle_resolution_selection)
        tc.exposure_changed.connect(lambda val: self.qt_cam_widget.set_exposure(val))
        tc.gain_changed.connect(
            lambda val: self.qt_cam_widget.set_gain(val)
        )  # Assumes gain is float
        # tc.brightness_changed # Not directly used for TIS, remove or map if needed
        tc.auto_exposure_toggled.connect(
            lambda checked: self.qt_cam_widget.set_auto_exposure(checked)
        )
        tc.roi_changed.connect(self.qt_cam_widget.set_software_roi)
        tc.roi_reset_requested.connect(self.qt_cam_widget.reset_roi_to_default)

        # Plot related signals from TopControlPanel (which forwards from PlotControlPanel)
        pc_controls = tc.plot_controls  # Alias for PlotControlPanel via TopControlPanel
        pc_controls.x_axis_limits_changed.connect(
            self.pressure_plot_widget.set_manual_x_limits
        )
        pc_controls.y_axis_limits_changed.connect(
            self.pressure_plot_widget.set_manual_y_limits
        )
        pc_controls.export_plot_image_requested.connect(
            self.pressure_plot_widget.export_as_image
        )
        # Reset button on plot controls directly connected to plot_widget's reset_zoom
        pc_controls.reset_btn.clicked.connect(
            lambda: self.pressure_plot_widget.reset_zoom(
                pc_controls.auto_x_cb.isChecked(), pc_controls.auto_y_cb.isChecked()
            )
        )

    def _connect_camera_widget_signals(self):
        # Signals from QtCameraWidget itself
        self.qt_cam_widget.camera_resolutions_updated.connect(
            self.top_ctrl.camera_controls.update_camera_resolutions_list  # Connect to CameraControlPanel slot
        )
        self.qt_cam_widget.camera_properties_updated.connect(
            self.top_ctrl.camera_controls.update_camera_properties_ui  # Connect to CameraControlPanel slot
        )
        self.qt_cam_widget.camera_error.connect(
            self._handle_camera_error
        )  # Renamed slot
        self.qt_cam_widget.frame_ready.connect(self._handle_new_camera_frame)

    # --- Camera Control Slots ---
    @pyqtSlot(object)  # Receives ic4.DeviceInfo or None
    def _handle_camera_selection(self, device_info_obj):
        log.debug(
            f"MainWindow: Camera selection changed. DeviceInfo: {device_info_obj}"
        )
        if ic4 and isinstance(device_info_obj, ic4.DeviceInfo):
            self.qt_cam_widget.set_active_camera_device(device_info_obj)
            # Camera properties will be updated via signals from QtCameraWidget after it connects
            # Start recording action might be enabled if serial is also connected
            self._update_recording_actions_enable_state()
        elif device_info_obj is None:  # "Select Camera..." or "No TIS Camera"
            self.qt_cam_widget.set_active_camera_device(None)
            self.top_ctrl.camera_controls.disable_all_controls()
            self.top_ctrl.camera_controls.update_camera_resolutions_list([])
            self._update_recording_actions_enable_state()
        else:
            log.warning(
                f"MainWindow: Received unknown camera data type: {type(device_info_obj)}"
            )
            self.qt_cam_widget.set_active_camera_device(None)

    @pyqtSlot(str)  # Receives "WidthxHeight (PixelFormat)" string
    def _handle_resolution_selection(self, resolution_str: str):
        log.debug(f"MainWindow: Resolution selection changed to: {resolution_str}")
        self.qt_cam_widget.set_active_resolution_str(resolution_str)
        # Update internal knowledge of width/height for recording, if possible
        try:
            if "x" in resolution_str:
                parts = resolution_str.split("x")
                self.current_camera_frame_width = int(parts[0])
                h_part = parts[1].split(" ")[
                    0
                ]  # Get height before potential format string
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
        # self.top_ctrl.camera_controls.disable_all_controls() # QtCameraWidget might show error on viewfinder
        # Consider if stopping recording or other actions are needed
        if self._is_recording:
            QMessageBox.warning(
                self,
                "Recording Problem",
                f"Camera error occurred: {error_message}\nRecording will be stopped.",
            )
            self._trigger_stop_recording()
        self._update_recording_actions_enable_state()

    # --- Serial Communication Slots ---
    def _toggle_serial_connection(self):
        if self._serial_thread and self._serial_thread.isRunning():
            log.info("MainWindow: Attempting to stop serial thread.")
            self._serial_thread.stop()  # stop() should make it emit finished signal
        else:
            selected_port_variant = self.serial_port_combobox.currentData()
            port_path = (
                selected_port_variant.value()
                if selected_port_variant is not None
                else None
            )

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
                # Ensure previous thread is fully gone if it crashed without emitting 'finished'
                if self._serial_thread:
                    if not self._serial_thread.wait(100):  # Brief wait
                        log.warning(
                            "Previous serial thread instance detected, terminating before starting new."
                        )
                        self._serial_thread.terminate()
                    self._serial_thread = None

                self._serial_thread = SerialThread(
                    port=port_path, parent=self
                )  # Pass parent for auto-cleanup by Qt
                self._serial_thread.data_ready.connect(self._handle_new_serial_data)
                self._serial_thread.error_occurred.connect(self._handle_serial_error)
                self._serial_thread.status_changed.connect(
                    self._handle_serial_status_change
                )
                self._serial_thread.finished.connect(
                    self._handle_serial_thread_finished
                )  # Important for cleanup
                self._serial_thread.start()
            except Exception as e:
                log.exception("MainWindow: Failed to create or start SerialThread.")
                QMessageBox.critical(
                    self, "Serial Error", f"Could not start serial communication: {e}"
                )
                self._serial_thread = None  # Ensure it's None on failure
                self._update_recording_actions_enable_state()

    @pyqtSlot(str)  # status_message from SerialThread
    def _handle_serial_status_change(self, status_message: str):
        log.info(f"MainWindow: Serial status changed - {status_message}")
        self.statusBar().showMessage(f"PRIM Device: {status_message}", 4000)

        is_connected = "connected" in status_message.lower()
        self.top_ctrl.update_connection_status(status_message, is_connected)

        if is_connected:
            self.connect_serial_action.setIcon(self.icon_disconnect)
            self.connect_serial_action.setText("Disconnect PRIM Device")
            self.serial_port_combobox.setEnabled(False)
            self.pressure_plot_widget.clear_plot()  # Clear plot on new connection
        else:  # Disconnected or error states
            self.connect_serial_action.setIcon(self.icon_connect)
            self.connect_serial_action.setText("Connect PRIM Device")
            self.serial_port_combobox.setEnabled(True)
            # self.pressure_plot_widget._update_placeholder("PRIM device disconnected.") # If method exists

            if (
                self._is_recording and "error" in status_message.lower()
            ):  # Stop recording if error led to disconnect
                QMessageBox.warning(
                    self,
                    "Recording Stopped",
                    f"PRIM device disconnected due to an error: {status_message}\nRecording has been stopped.",
                )
                self._trigger_stop_recording()
            elif (
                "disconnected" in status_message.lower() and self._is_recording
            ):  # Planned disconnect
                QMessageBox.information(
                    self,
                    "Recording Stopped",
                    "PRIM device disconnected.\nRecording has been stopped.",
                )
                self._trigger_stop_recording()

        self._update_recording_actions_enable_state()

    @pyqtSlot(str)  # error_message from SerialThread
    def _handle_serial_error(self, error_message: str):
        log.error(f"MainWindow: Serial Error Received - {error_message}")
        # Status change might already cover UI updates, but statusbar can be more specific here.
        self.statusBar().showMessage(f"PRIM Device Error: {error_message}", 6000)
        # _handle_serial_status_change will likely be called too by the thread for a disconnect status

    @pyqtSlot()  # Connected to serial_thread.finished
    def _handle_serial_thread_finished(self):
        log.info("MainWindow: SerialThread has finished.")
        # SerialThread itself will emit a "Disconnected" status_changed signal usually before finishing.
        # If it finished unexpectedly, make sure UI reflects disconnected state.
        if (
            self._serial_thread is self.sender()
        ):  # Check if it's the current thread instance
            self._serial_thread = None  # Dereference
            # Ensure UI reflects disconnected state if not already handled by status_changed
            current_status_text = self.top_ctrl.conn_lbl.text().lower()
            if "connected" in current_status_text:  # If UI still shows connected
                self._handle_serial_status_change("Disconnected (thread finished)")
            log.debug("MainWindow: _serial_thread dereferenced.")

    @pyqtSlot(int, float, float)  # frameCount, time_s, pressure from SerialThread
    def _handle_new_serial_data(self, frame_idx: int, time_s: float, pressure: float):
        self.top_ctrl.update_prim_data(frame_idx, time_s, pressure)

        auto_x = self.top_ctrl.plot_controls.auto_x_cb.isChecked()
        auto_y = self.top_ctrl.plot_controls.auto_y_cb.isChecked()
        self.pressure_plot_widget.update_plot(time_s, pressure, auto_x, auto_y)

        if self.dock_console.isVisible():  # Log to internal console if visible
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
                self._trigger_stop_recording()  # Stop recording on CSV error

    # --- Recording Logic ---
    def _update_recording_actions_enable_state(self):
        can_start_recording = (
            self._serial_thread
            and self._serial_thread.isRunning()
            and self.qt_cam_widget.current_camera_is_active()
            and not self._is_recording
        )
        self.start_recording_action.setEnabled(can_start_recording)
        self.stop_recording_action.setEnabled(self._is_recording)

    @pyqtSlot(QImage, object)  # qimg from QtCameraWidget, frame_obj (mem_ptr)
    def _handle_new_camera_frame(self, qimage: QImage, frame_obj: object):
        # Update internal knowledge of frame size if it's the first valid frame
        # This is just a fallback, resolution selection should be primary source
        if self.current_camera_frame_width == 0 and qimage and not qimage.isNull():
            self.current_camera_frame_width = qimage.width()
            self.current_camera_frame_height = qimage.height()
            log.info(
                f"MainWindow: Frame size updated from first frame: {qimage.width()}x{qimage.height()}"
            )

        if (
            self._is_recording
            and self.trial_recorder
            and qimage
            and not qimage.isNull()
        ):
            try:
                # Convert QImage to NumPy array for the recorder
                # Assuming Grayscale8 format from the camera thread for DMK
                if qimage.format() == QImage.Format_Grayscale8:
                    ptr = qimage.constBits()
                    # Ensure the size is correct for the buffer
                    expected_size = qimage.height() * qimage.bytesPerLine()
                    ptr.setsize(expected_size)  # Critical: Set size for the memory view

                    # Create a NumPy array view, then copy if SimpleVideoRecorder needs its own copy
                    # Reshape: (height, width). For Grayscale8, bytesPerLine == width.
                    numpy_frame = np.array(ptr, dtype=np.uint8).reshape(
                        qimage.height(), qimage.width()
                    )
                    self.trial_recorder.write_video_frame(
                        numpy_frame.copy()
                    )  # Pass a copy

                elif (
                    qimage.format() == QImage.Format_RGB888
                ):  # Example if supporting color
                    ptr = qimage.constBits()
                    expected_size = qimage.height() * qimage.bytesPerLine()
                    ptr.setsize(expected_size)
                    numpy_frame = np.array(ptr, dtype=np.uint8).reshape(
                        qimage.height(), qimage.width(), 3
                    )  # For RGB888
                    self.trial_recorder.write_video_frame(numpy_frame.copy())
                else:
                    log.warning(
                        f"Unsupported QImage format for recording: {qimage.format()}. Cannot write video frame."
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

        # Session Details Dialog
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
        notes_edit.setFixedHeight(80)  # Adjust height as needed
        form_layout.addRow("Notes:", notes_edit)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        form_layout.addRow(button_box)

        if dialog.exec_() != QDialog.Accepted:
            return  # User cancelled

        session_name = (
            session_name_edit.text().strip() or session_name_edit.placeholderText()
        )
        # operator_name = operator_edit.text().strip() # Store these if needed
        # session_notes = notes_edit.toPlainText().strip()

        # Create folder for this session's results
        # Sanitize session_name for use as a folder name (remove invalid chars)
        safe_session_name = "".join(
            c if c.isalnum() or c in (" ", "_", "-") else "_" for c in session_name
        ).rstrip()
        safe_session_name = safe_session_name.replace(
            " ", "_"
        )  # Replace spaces with underscores

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
        self.last_trial_basepath = session_folder_path  # Store the folder path

        # Get frame size for recorder (use current camera settings)
        # Prefer properties from QtCameraWidget or SDKCameraThread if available and reliable
        # For now, use the values updated by resolution selection or first frame
        frame_w = self.current_camera_frame_width
        frame_h = self.current_camera_frame_height
        if frame_w <= 0 or frame_h <= 0:  # Fallback if not updated
            log.warning(
                f"Invalid frame size {frame_w}x{frame_h} for recording, falling back to DEFAULT_FRAME_SIZE"
            )
            frame_w, frame_h = DEFAULT_FRAME_SIZE

        video_ext_str = (
            self.video_format_combobox.currentData().value()
        )  # Should be 'avi' or 'tif'
        video_codec_str = DEFAULT_VIDEO_CODEC  # From config, used if 'avi'

        log.info(
            f"Starting recording: Base='{base_output_filename}', FPS={DEFAULT_FPS}, Size={frame_w}x{frame_h}, Format={video_ext_str}"
        )

        try:
            self.trial_recorder = TrialRecorder(
                basepath=base_output_filename,  # TrialRecorder appends timestamp and ext
                fps=DEFAULT_FPS,  # From config
                frame_size=(frame_w, frame_h),
                video_ext=video_ext_str,
                video_codec=video_codec_str,
            )
            if (
                not self.trial_recorder.is_recording
            ):  # Check if recorder initialized successfully
                raise RuntimeError("TrialRecorder failed to initialize or start.")
        except Exception as e:
            log.exception("MainWindow: Failed to initialize TrialRecorder.")
            QMessageBox.critical(
                self, "Recording Error", f"Could not start recorder: {e}"
            )
            self.trial_recorder = None
            return

        # Frame connection handled by _handle_new_camera_frame when _is_recording is true
        self._is_recording = True
        self.start_recording_action.setIcon(self.icon_recording_active)  # Update icon
        self._update_recording_actions_enable_state()
        self.pressure_plot_widget.clear_plot()  # Clear plot for new recording
        self.statusBar().showMessage(
            f"Recording Started: {session_name}", 0
        )  # Persistent message

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
                # Offer to open folder
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
                            elif sys.platform == "darwin":  # macOS
                                os.system(f'open "{self.last_trial_basepath}"')
                            else:  # Linux and other POSIX
                                os.system(f'xdg-open "{self.last_trial_basepath}"')
                        except Exception as e_open:
                            log.error(
                                f"Could not open folder {self.last_trial_basepath}: {e_open}"
                            )

            except Exception as e:
                log.exception("MainWindow: Error during trial_recorder.stop().")
                self.statusBar().showMessage("Error stopping recorder.", 5000)
            finally:
                self.trial_recorder = None  # Clear recorder instance

        self._is_recording = False
        self.start_recording_action.setIcon(self.icon_record_start)  # Reset icon
        self._update_recording_actions_enable_state()

    # --- Plot Actions ---
    @pyqtSlot()
    def _clear_pressure_plot(self):
        self.pressure_plot_widget.clear_plot()
        self.statusBar().showMessage("Pressure plot cleared.", 3000)

    @pyqtSlot()
    def _export_plot_data_as_csv(self):
        if not self.pressure_plot_widget.times:  # Check if there's data in the plot
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
            return  # User cancelled

        try:
            with open(file_path, "w", newline="") as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(["time_s", "pressure_mmHg"])  # Header row
                for t, p in zip(
                    self.pressure_plot_widget.times, self.pressure_plot_widget.pressures
                ):
                    writer.writerow(
                        [f"{t:.6f}", f"{p:.6f}"]
                    )  # Format to desired precision
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

    # --- Help / About ---
    @pyqtSlot()
    def _show_about_dialog(self):
        QMessageBox.about(
            self, f"About {APP_NAME}", ABOUT_TEXT
        )  # ABOUT_TEXT from config

    # --- Session Timer ---
    def _update_app_session_time(self):
        self._app_session_seconds += 1
        hours = self._app_session_seconds // 3600
        minutes = (self._app_session_seconds % 3600) // 60
        seconds = self._app_session_seconds % 60
        self.app_session_time_label.setText(
            f"Session: {hours:02}:{minutes:02}:{seconds:02}"
        )

    # --- Application Close Event ---
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
                self._trigger_stop_recording()  # Stop recording gracefully
            else:
                event.ignore()  # User chose not to exit
                return

        # Ensure serial thread is stopped
        if self._serial_thread and self._serial_thread.isRunning():
            log.info("MainWindow: Stopping serial thread before exiting...")
            self._serial_thread.stop()
            if not self._serial_thread.wait(2000):  # Wait up to 2s
                log.warning(
                    "SerialThread did not stop gracefully on exit, terminating."
                )
                self._serial_thread.terminate()
            self._serial_thread = None

        # Ensure camera widget resources are released (it has its own closeEvent)
        log.info("MainWindow: Calling close on QtCameraWidget.")
        self.qt_cam_widget.close()  # This will trigger its closeEvent

        log.info(f"{APP_NAME} is shutting down.")
        super().closeEvent(event)
