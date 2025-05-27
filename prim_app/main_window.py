# PRIM-QTAPP/prim_app/main_window.py
import os
import sys
import logging
import csv
import json  # For loading camera profiles
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QDockWidget,
    QTextEdit,
    # QPushButton, # Not directly used, but QAction is
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
    # QSizePolicy, # Not directly used in this snippet
    QMessageBox,
)
from PyQt5.QtCore import Qt, pyqtSlot, QTimer, QVariant, QDateTime, QSize, QThread
from PyQt5.QtGui import QIcon, QKeySequence

# Module-level access to prim_app's functions and state flags
import prim_app
from prim_app import initialize_ic4_with_cti, is_ic4_fully_initialized

from utils.app_settings import (
    save_app_setting,
    load_app_setting,
    SETTING_CTI_PATH,
    SETTING_LAST_CAMERA_SERIAL,
    SETTING_LAST_PROFILE_NAME,
)
from utils.config import (
    CAMERA_PROFILES_DIR,
    DEFAULT_FPS,
    DEFAULT_FRAME_SIZE,
    APP_NAME,
    APP_VERSION,
    PRIM_RESULTS_DIR,
    DEFAULT_VIDEO_EXTENSION,
    DEFAULT_VIDEO_CODEC,
    # SUPPORTED_FORMATS, # Not directly used in this file snippet
    ABOUT_TEXT,
)

from ui.control_panels.top_control_panel import TopControlPanel
from ui.control_panels.camera_control_panel import CameraControlPanel
from ui.canvas.gl_viewfinder import GLViewfinder
from ui.canvas.pressure_plot_widget import PressurePlotWidget
from threads.sdk_camera_thread import SDKCameraThread
from camera.setup_wizard import CameraSetupWizard
from threads.serial_thread import SerialThread
from recording import RecordingWorker
from utils.utils import list_serial_ports


log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._serial_thread = None
        self._recording_worker = None
        self._is_recording = False
        self.camera_thread = None
        self.camera_panel = None
        self.camera_view = None
        self.bottom_split = None
        self.camera_settings = {}

        self._init_paths_and_icons()
        self._build_console_log_dock()
        self._build_central_widget_layout()
        self._build_menus()
        self._build_main_toolbar()
        self._build_status_bar()

        if self.top_ctrl and self.pressure_plot_widget:
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

        self.setWindowTitle(
            f"{prim_app.APP_NAME} - v{prim_app.CONFIG_APP_VERSION or '1.0'}"
        )

        self._check_and_prompt_for_cti_on_startup()

        if is_ic4_fully_initialized():
            QTimer.singleShot(0, self._try_load_last_camera)
        else:
            log.info("IC4 not fully initialized, skipping auto-load of last camera.")
            self.statusBar().showMessage(
                "IC4 SDK not fully configured. Camera features require CTI setup via menu.",
                5000,
            )

        self.showMaximized()
        QTimer.singleShot(
            50, self._set_initial_splitter_sizes
        )  # Small delay for layout
        self._set_initial_control_states()
        log.info("MainWindow initialized.")

    def _set_initial_splitter_sizes(self):  # Definition added back
        if self.bottom_split:
            total_width = self.bottom_split.size().width()
            if total_width > 0:
                left = int(total_width * 0.65)
                right = total_width - left
                self.bottom_split.setSizes([left, right])
            else:
                # This might be called before the window is fully shown and has a size.
                # A QTimer.singleShot with a slightly longer delay, or connecting to showEvent
                # might be more robust if this warning appears frequently.
                log.debug(
                    "Cannot set initial splitter sizes yet, total width is 0 (may resolve after window is fully shown)."
                )
        else:
            log.warning(
                "bottom_split not initialized when _set_initial_splitter_sizes was called."
            )

    def _check_and_prompt_for_cti_on_startup(self):
        if not is_ic4_fully_initialized() and prim_app.IC4_AVAILABLE:
            log.info(
                "IC4 SDK is available but not fully configured. Prompting for CTI file."
            )
            QMessageBox.information(
                self,
                "Camera SDK Setup Required",
                "The IC Imaging Control SDK needs a GenTL Producer file (.cti) to work with your camera(s).\n\n"
                "This is usually provided by your camera manufacturer (e.g., The Imaging Source).\n\n"
                "Please select the .cti file for your camera hardware.",
            )

            suggested_cti_dir = (
                os.path.dirname(load_app_setting(SETTING_CTI_PATH, ""))
                if load_app_setting(SETTING_CTI_PATH)
                else ""
            )

            cti_path, _ = QFileDialog.getOpenFileName(
                self,
                "Select GenTL Producer File (.cti)",
                suggested_cti_dir,
                "CTI Files (*.cti);;All Files (*)",
            )
            if cti_path and os.path.exists(cti_path):
                try:
                    initialize_ic4_with_cti(cti_path)
                    if is_ic4_fully_initialized():
                        save_app_setting(SETTING_CTI_PATH, cti_path)
                        QMessageBox.information(
                            self,
                            "CTI Loaded",
                            f"GenTL Producer loaded: {os.path.basename(cti_path)}\n"
                            "Use 'Camera > Setup Camera...' to configure your specific camera.",
                        )
                        self.statusBar().showMessage(
                            f"CTI loaded: {os.path.basename(cti_path)}", 5000
                        )
                    else:
                        QMessageBox.critical(
                            self,
                            "CTI Load Error",
                            f"Failed to fully initialize SDK with: {os.path.basename(cti_path)}.\n"
                            "Check logs for details. Camera features may be limited.",
                        )
                except Exception as e:
                    QMessageBox.critical(
                        self,
                        "CTI Loading Exception",
                        f"Error loading {os.path.basename(cti_path)}: {e}",
                    )
                    log.exception(
                        f"Exception initializing CTI '{cti_path}' via prompt."
                    )
            elif cti_path:
                QMessageBox.warning(
                    self, "File Not Found", f"Selected CTI file not found: {cti_path}"
                )
            else:
                QMessageBox.warning(
                    self,
                    "CTI Not Selected",
                    "No CTI file selected. Camera features require CTI setup via 'Camera > Change CTI File...'.",
                )
        elif is_ic4_fully_initialized():
            log.info("IC4 already fully initialized. Skipping startup CTI prompt.")
            self.statusBar().showMessage(
                f"IC4 initialized with CTI: {os.path.basename(load_app_setting(SETTING_CTI_PATH, 'Unknown CTI'))}",
                5000,
            )
        elif not prim_app.IC4_AVAILABLE and not os.environ.get(
            "PRIM_APP_TESTING_NO_IC4"
        ):
            log.warning("IC4_AVAILABLE is false. Camera features disabled.")

    def _connect_camera_signals(self):
        if not self.camera_thread or not self.camera_panel or not self.camera_view:
            log.error(
                "Cannot connect camera signals, essential UI or thread components missing."
            )
            return True

        th = self.camera_thread
        cp = self.camera_panel

        # Disconnect previous signals to avoid multiple calls if re-connecting
        for signal_name in [
            "currentTextChanged",
            "stateChanged",
            "valueChanged",
            "clicked",
        ]:
            for widget in [
                cp.res_combo,
                cp.pix_combo,
                cp.auto_exp_cb,
                cp.exp_spin,
                cp.gain_slider,
                cp.fps_spin,
                cp.start_stream,
                cp.stop_stream,
            ]:
                signal = getattr(widget, signal_name, None)
                if signal:
                    try:
                        while True:
                            signal.disconnect()  # Disconnect all slots
                    except (TypeError, RuntimeError):
                        pass  # No more connections or error disconnecting

        for th_signal_name in [
            "resolutions_updated",
            "pixel_formats_updated",
            "fps_range_updated",
            "exposure_range_updated",
            "gain_range_updated",
            "auto_exposure_updated",
            "properties_updated",
            "frame_ready",
            "camera_error",
        ]:
            th_signal = getattr(th, th_signal_name, None)
            if th_signal:
                try:
                    while True:
                        th_signal.disconnect()
                except (TypeError, RuntimeError):
                    pass

        # Thread -> Panel
        th.resolutions_updated.connect(
            lambda res_list: (
                cp.res_combo.clear(),
                cp.res_combo.addItems(res_list or []),
            )
        )
        th.pixel_formats_updated.connect(
            lambda fmt_list: (
                cp.pix_combo.clear(),
                cp.pix_combo.addItems(fmt_list or []),
            )
        )

        def set_profile_aware_value(
            spinbox,
            setting_key_primary,
            setting_key_secondary,
            sdk_value,
            default_value,
        ):
            profile_val = self.camera_settings.get("defaults", {}).get(
                setting_key_primary
            )
            if profile_val is None and setting_key_secondary:
                profile_val = self.camera_settings.get("defaults", {}).get(
                    setting_key_secondary
                )

            val_to_set = default_value  # Start with the ultimate fallback
            if sdk_value is not None:
                val_to_set = sdk_value  # Prefer SDK value if no profile
            if profile_val is not None:
                val_to_set = profile_val  # Profile overrides SDK if present

            try:
                spinbox.setValue(val_to_set)
            except Exception as e:
                log.error(
                    f"Error setting value '{val_to_set}' for {setting_key_primary} on {spinbox}: {e}"
                )
                spinbox.setValue(default_value)  # Fallback on error

        th.fps_range_updated.connect(
            lambda lo, hi: (
                cp.fps_spin.setRange(lo, hi),
                set_profile_aware_value(
                    cp.fps_spin, "AcquisitionFrameRate", "FPS", hi, DEFAULT_FPS
                ),
            )
        )
        th.exposure_range_updated.connect(
            lambda lo, hi: (
                cp.exp_spin.setRange(lo, hi),
                set_profile_aware_value(
                    cp.exp_spin, "ExposureTime", "Exposure", lo, lo
                ),
            )
        )
        th.gain_range_updated.connect(
            lambda lo, hi: (
                cp.gain_slider.setRange(int(lo), int(hi)),
                set_profile_aware_value(cp.gain_slider, "Gain", None, int(lo), int(lo)),
            )
        )
        th.auto_exposure_updated.connect(cp.auto_exp_cb.setChecked)
        th.properties_updated.connect(
            lambda props: cp.exp_spin.setValue(
                props.get("ExposureTime", cp.exp_spin.value())
            )
        )
        th.properties_updated.connect(
            lambda props: cp.gain_slider.setValue(
                int(props.get("Gain", cp.gain_slider.value()))
            )
        )

        # Panel -> Thread
        cp.resolution_changed.connect(
            lambda r_str: r_str
            and th.apply_node_settings(
                {"Width": int(r_str.split("x")[0]), "Height": int(r_str.split("x")[1])}
            )
        )
        cp.pixel_format_changed.connect(
            lambda f_str: f_str and th.apply_node_settings({"PixelFormat": f_str})
        )
        cp.auto_exposure_toggled.connect(
            lambda ae_on: th.apply_node_settings(
                {"ExposureAuto": "Continuous" if ae_on else "Off"}
            )
        )
        cp.exposure_changed.connect(
            lambda v: th.apply_node_settings({"ExposureTime": v})
        )
        cp.gain_changed.connect(
            lambda v_float: th.apply_node_settings({"Gain": v_float})
        )
        cp.fps_changed.connect(
            lambda v: th.apply_node_settings({"AcquisitionFrameRate": v})
        )

        cp.start_stream.clicked.connect(th.start)
        cp.stop_stream.clicked.connect(th.stop)

        th.frame_ready.connect(self.camera_view.update_frame)
        th.camera_error.connect(self._on_camera_error)
        log.info("Camera signals connected.")
        return False

    def _start_sdk_camera_thread(self, camera_serial, fps, initial_settings=None):
        if self.camera_thread and self.camera_thread.isRunning():
            log.info("Stopping existing camera thread before starting new one...")
            self.camera_thread.stop()
            if not self.camera_thread.wait(2000):
                log.warning("Old camera thread did not stop gracefully, terminating.")
                self.camera_thread.terminate()
                self.camera_thread.wait(500)
        if self.camera_thread:  # Ensure old thread is fully gone before reassigning
            self.camera_thread.deleteLater()
        self.camera_thread = None

        log.info(
            f"Initializing SDKCameraThread for device: {camera_serial} at {fps} FPS"
        )
        self.camera_thread = SDKCameraThread(
            device_name=camera_serial, fps=fps, parent=self
        )
        self.camera_settings["cameraSerialPattern"] = camera_serial

        if self._connect_camera_signals():
            log.error(
                "Failed to connect camera signals during _start_sdk_camera_thread. Aborting."
            )
            if self.camera_thread:
                self.camera_thread.deleteLater()
            self.camera_thread = None
            return

        def apply_initial_cam_settings():
            if self.camera_thread and initial_settings:
                log.info(
                    f"Applying initial settings post-start: {list(initial_settings.keys())}"
                )
                self.camera_thread.apply_node_settings(initial_settings)

        if initial_settings:
            QTimer.singleShot(300, apply_initial_cam_settings)

        self.camera_thread.start()
        self.statusBar().showMessage(
            f"Camera '{self.camera_settings.get('model', camera_serial)}' starting...",
            5000,
        )
        if self.camera_panel:
            self.camera_panel.setEnabled(True)

    def _try_load_last_camera(self):
        if not is_ic4_fully_initialized():
            log.info("IC4 not fully initialized, cannot auto-load last camera.")
            return

        last_profile_name = load_app_setting(SETTING_LAST_PROFILE_NAME)
        if not last_profile_name:
            log.info("No last camera profile saved. Use 'Camera > Setup Camera...'.")
            self.statusBar().showMessage(
                "No default camera profile. Use Camera > Setup Camera.", 5000
            )
            if self.camera_panel:
                self.camera_panel.setEnabled(False)  # No camera to control
            return

        profile_path = os.path.join(CAMERA_PROFILES_DIR, f"{last_profile_name}.json")
        if not os.path.exists(profile_path):
            log.warning(
                f"Last camera profile '{last_profile_name}' not found at {profile_path}."
            )
            self.statusBar().showMessage(
                f"Profile '{last_profile_name}' missing. Use Camera > Setup Camera.",
                5000,
            )
            save_app_setting(SETTING_LAST_PROFILE_NAME, None)
            save_app_setting(SETTING_LAST_CAMERA_SERIAL, None)
            if self.camera_panel:
                self.camera_panel.setEnabled(False)
            return

        try:
            with open(profile_path, "r") as f:
                profile_data = json.load(f)
            log.info(f"Loaded last camera profile: {last_profile_name}")
            self.camera_settings = profile_data

            cam_serial = profile_data.get("serialPattern")
            if not cam_serial:
                log.error(f"Profile '{last_profile_name}' missing 'serialPattern'.")
                if self.camera_panel:
                    self.camera_panel.setEnabled(False)
                return

            all_initial_settings = {
                **profile_data.get("defaults", {}),
                **profile_data.get("advanced", {}),
            }
            target_fps = all_initial_settings.get("AcquisitionFrameRate", DEFAULT_FPS)

            profile_cti = profile_data.get("ctiPathUsed")
            current_cti = load_app_setting(SETTING_CTI_PATH)
            if (
                profile_cti
                and current_cti
                and os.path.normpath(profile_cti) != os.path.normpath(current_cti)
            ):
                log.warning(
                    f"Profile '{last_profile_name}' CTI '{os.path.basename(profile_cti)}' "
                    f"differs from current CTI '{os.path.basename(current_cti)}'."
                )
                QMessageBox.warning(
                    self,
                    "Profile/CTI Mismatch",
                    f"Profile '{last_profile_name}' was saved with CTI:\n{os.path.basename(profile_cti)}\n\n"
                    f"Currently loaded CTI is:\n{os.path.basename(current_cti)}\n\n"
                    "Attempting connection. If issues occur, re-run Camera Setup or use 'Camera > Change CTI File...'.",
                )

            self._start_sdk_camera_thread(cam_serial, target_fps, all_initial_settings)
        except json.JSONDecodeError:
            log.error(f"Corrupted profile file: {profile_path}")
            QMessageBox.critical(
                self,
                "Profile Error",
                f"Could not parse profile: {last_profile_name}.json. Please delete it and re-setup.",
            )
            if self.camera_panel:
                self.camera_panel.setEnabled(False)
        except Exception as e:
            log.exception(
                f"Failed to auto-load or start last camera '{last_profile_name}': {e}"
            )
            QMessageBox.critical(
                self,
                "Camera Auto-Load Error",
                f"Could not auto-start '{last_profile_name}':\n{e}",
            )
            if self.camera_panel:
                self.camera_panel.setEnabled(False)

    def _run_camera_setup(self):
        if not is_ic4_fully_initialized():
            QMessageBox.warning(
                self,
                "Camera SDK Not Ready",
                "The camera SDK (IC4) is not configured with a CTI file. "
                "Please use 'Camera > Change CTI File...' to select one first, "
                "or ensure IC Imaging Control SDK is correctly installed if the problem persists.",
            )
            return

        wizard = CameraSetupWizard(self)
        if wizard.exec_() != QDialog.Accepted:
            log.info("Camera Setup Wizard cancelled.")
            return

        self.camera_settings = wizard.settings
        log.info(
            f"Camera Setup Wizard completed. Settings acquired: {list(self.camera_settings.keys())}"
        )

        profile_name_saved_as = self.camera_settings.get("profileNameSavedAs")
        camera_serial = self.camera_settings.get("cameraSerialPattern")

        if profile_name_saved_as:
            save_app_setting(SETTING_LAST_PROFILE_NAME, profile_name_saved_as)
            log.info(f"Saved last profile name hint: {profile_name_saved_as}")
        if camera_serial:
            save_app_setting(SETTING_LAST_CAMERA_SERIAL, camera_serial)
            log.info(f"Saved last camera serial hint: {camera_serial}")

        target_fps = self.camera_settings.get("defaults", {}).get(
            "AcquisitionFrameRate", DEFAULT_FPS
        )
        all_initial_settings = {
            **self.camera_settings.get("defaults", {}),
            **self.camera_settings.get("advanced", {}),
        }

        if camera_serial:
            self._start_sdk_camera_thread(
                camera_serial, target_fps, all_initial_settings
            )
        else:
            log.error("No camera serial pattern in wizard settings post-completion.")
            QMessageBox.critical(
                self, "Setup Error", "Camera setup error: No camera serial identified."
            )

    def _init_paths_and_icons(self):
        base = os.path.dirname(os.path.abspath(__file__))
        icon_dir = os.path.join(base, "ui", "icons")
        if not os.path.isdir(icon_dir):
            alt_icon_dir = os.path.join(os.path.dirname(base), "ui", "icons")
            if os.path.isdir(alt_icon_dir):
                icon_dir = alt_icon_dir
            else:
                log.warning(f"Icon directory not found at {icon_dir} or {alt_icon_dir}")

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
        layout = QVBoxLayout(central)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(3)
        top_row = QWidget()
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(5)
        self.camera_panel = CameraControlPanel(self)
        top_layout.addWidget(self.camera_panel)
        self.camera_panel.setEnabled(False)
        self.top_ctrl = TopControlPanel(self)
        top_layout.addWidget(self.top_ctrl)
        if hasattr(self.top_ctrl, "plot_controls"):
            top_layout.addWidget(self.top_ctrl.plot_controls)
        else:
            log.error("self.top_ctrl.plot_controls not found.")
        layout.addWidget(top_row)
        self.bottom_split = QSplitter(Qt.Horizontal)
        self.bottom_split.setChildrenCollapsible(False)
        self.camera_view = GLViewfinder(self)
        self.bottom_split.addWidget(self.camera_view)
        self.pressure_plot_widget = PressurePlotWidget(self)
        self.bottom_split.addWidget(self.pressure_plot_widget)
        self.bottom_split.setStretchFactor(0, 1)
        self.bottom_split.setStretchFactor(1, 1)
        layout.addWidget(self.bottom_split, 1)
        self.setCentralWidget(central)

    def _build_menus(self):
        mb = self.menuBar()
        fm = mb.addMenu("&File")
        exp_data_act = QAction(
            "Export Plot &Data (CSV)…", self, triggered=self._export_plot_data_as_csv
        )
        fm.addAction(exp_data_act)
        exp_img_act = QAction("Export Plot &Image…", self)
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
        app_name_for_menu = (
            prim_app.APP_NAME if hasattr(prim_app, "APP_NAME") else "Application"
        )
        about_act = QAction(
            f"&About {app_name_for_menu}", self, triggered=self._show_about_dialog
        )
        hm.addAction(about_act)
        hm.addAction("About &Qt", QApplication.instance().aboutQt)

        cam_menu = mb.addMenu("&Camera")
        setup_cam_act = QAction("Setup Camera…", self, triggered=self._run_camera_setup)
        cam_menu.addAction(setup_cam_act)
        change_cti_act = QAction(
            "Change CTI File...", self, triggered=self._change_cti_file
        )
        cam_menu.addAction(change_cti_act)

    def _change_cti_file(self):
        cti_path, _ = QFileDialog.getOpenFileName(self, "Select CTI File", "", "*.cti")
        if not cti_path:
            return
        try:
            initialize_ic4_with_cti(cti_path)
            QMessageBox.information(self, "CTI Loaded", f"Loaded CTI:\n{cti_path}")
        except Exception as exc:
            QMessageBox.critical(self, "CTI Exception", str(exc))

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
        self.serial_port_combobox.addItem("🔌 Simulated Data", QVariant())
        ports = list_serial_ports()
        if ports:
            [
                self.serial_port_combobox.addItem(
                    f"{os.path.basename(p)} ({d})", QVariant(p)
                )
                for p, d in ports
            ]
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
        sb = self.statusBar() or QStatusBar(self)
        self.setStatusBar(sb)
        self.app_session_time_label = QLabel("Session: 00:00:00")
        sb.addPermanentWidget(self.app_session_time_label)
        self._app_session_seconds = 0
        self._app_session_timer = QTimer(self, interval=1000)
        self._app_session_timer.timeout.connect(self._update_app_session_time)
        self._app_session_timer.start()

    def _set_initial_control_states(self):
        if self.top_ctrl:
            self.top_ctrl.update_connection_status("Disconnected", False)
        if hasattr(self, "start_recording_action"):
            self.start_recording_action.setEnabled(False)
        if hasattr(self, "stop_recording_action"):
            self.stop_recording_action.setEnabled(False)
        if self.camera_panel:
            self.camera_panel.setEnabled(
                is_ic4_fully_initialized()
                and bool(load_app_setting(SETTING_LAST_PROFILE_NAME))
            )

    @pyqtSlot(str)
    def _handle_serial_status_change(self, status: str):
        log.info(f"Serial status: {status}")
        self.statusBar().showMessage(f"PRIM Device: {status}", 4000)
        connected = (
            "connected" in status.lower() or "opened serial port" in status.lower()
        )
        if self.top_ctrl:
            self.top_ctrl.update_connection_status(status, connected)
        if connected:
            self.connect_serial_action.setIcon(self.icon_disconnect)
            self.connect_serial_action.setText("Disconnect PRIM Device")
            self.serial_port_combobox.setEnabled(False)
            if self.pressure_plot_widget:
                self.pressure_plot_widget.clear_plot()
        else:
            self.connect_serial_action.setIcon(self.icon_connect)
            self.connect_serial_action.setText("Connect PRIM Device")
            self.serial_port_combobox.setEnabled(True)
            if self._is_recording:
                QMessageBox.warning(
                    self,
                    "Recording Auto-Stopped",
                    "PRIM device disconnected. Recording stopped.",
                )
                self._trigger_stop_recording()
        self._update_recording_actions_enable_state()

    @pyqtSlot(str)
    def _handle_serial_error(self, msg: str):
        log.error(f"Serial error: {msg}")
        self.statusBar().showMessage(f"Serial Error: {msg}", 6000)
        if "disconnecting" in msg.lower() or "error opening" in msg.lower():
            self._handle_serial_status_change(f"Error: {msg}. Disconnected.")
        self._update_recording_actions_enable_state()

    @pyqtSlot()
    def _handle_serial_thread_finished(self):
        log.info("SerialThread 'finished' signal received.")
        sender = self.sender()
        if self._serial_thread is sender:
            current_conn_text = (
                self.top_ctrl.conn_lbl.text().lower()
                if self.top_ctrl and hasattr(self.top_ctrl, "conn_lbl")
                else ""
            )
            if "connected" in current_conn_text or "opened" in current_conn_text:
                self._handle_serial_status_change("Disconnected")
            if self._serial_thread:
                self._serial_thread.deleteLater()
            self._serial_thread = None
            log.info("Current _serial_thread instance cleaned up.")
        elif sender:
            log.warning("Received 'finished' from orphaned SerialThread.")
            sender.deleteLater()
        else:
            log.warning("Received 'finished' from non-object sender.")
        self._update_recording_actions_enable_state()

    @pyqtSlot(int, float, float)
    def _handle_new_serial_data(self, idx: int, t: float, p: float):
        if (
            self.top_ctrl
            and hasattr(self.top_ctrl, "plot_controls")
            and self.top_ctrl.plot_controls
        ):
            self.top_ctrl.update_prim_data(idx, t, p)
            ax_auto = self.top_ctrl.plot_controls.auto_x_cb.isChecked()
            ay_auto = self.top_ctrl.plot_controls.auto_y_cb.isChecked()
            if self.pressure_plot_widget:
                self.pressure_plot_widget.update_plot(t, p, ax_auto, ay_auto)
        if (
            self.dock_console
            and self.dock_console.isVisible()
            and self.console_out_textedit
        ):
            self.console_out_textedit.append(
                f"PRIM Data: Idx={idx}, Time={t:.3f}s, P={p:.2f}"
            )
        if self._is_recording and self._recording_worker:
            try:
                self._recording_worker.add_csv_data(t, idx, p)
            except Exception:
                log.exception("CSV queue error.")
                self.statusBar().showMessage(
                    "CRITICAL: CSV queue error. Stop REC.", 5000
                )
                self._trigger_stop_recording()

    def _toggle_serial_connection(self):
        if self._serial_thread and self._serial_thread.isRunning():
            log.info("User stop serial.")
            self._serial_thread.stop()
        else:
            data = self.serial_port_combobox.currentData()
            port_to_use = data.value() if isinstance(data, QVariant) else data
            if (
                port_to_use is None
                and self.serial_port_combobox.currentText() != "🔌 Simulated Data"
            ):
                QMessageBox.warning(self, "Serial Connection", "Select valid port.")
                return
            log.info(f"User start serial: {port_to_use or 'Simulation'}")
            if self._serial_thread:
                log.warning("Old _serial_thread obj existed. Deleting.")
                self._serial_thread.deleteLater()
                self._serial_thread = None
            try:
                self._serial_thread = SerialThread(port=port_to_use, parent=self)
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
                log.exception("Failed to create/start SerialThread.")
                QMessageBox.critical(
                    self, "Serial Thread Error", f"Could not start serial: {e}"
                )
                if self._serial_thread:
                    self._serial_thread.deleteLater()
                self._serial_thread = None
                self._update_recording_actions_enable_state()

    def _update_recording_actions_enable_state(self):
        serial_is_ready = (
            self._serial_thread is not None and self._serial_thread.isRunning()
        )
        can_start = serial_is_ready and not self._is_recording
        can_stop = self._is_recording
        if hasattr(self, "start_recording_action"):
            self.start_recording_action.setEnabled(can_start)
        if hasattr(self, "stop_recording_action"):
            self.stop_recording_action.setEnabled(can_stop)

    def _trigger_start_recording_dialog(self):
        if not (self._serial_thread and self._serial_thread.isRunning()):
            QMessageBox.warning(self, "Cannot Record", "PRIM device inactive.")
            return
        if self._is_recording:
            QMessageBox.information(self, "Recording Active", "Session already active.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("New Recording Session")
        layout = QFormLayout(dialog)
        name_edit = QLineEdit(
            f"Session_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}"
        )
        layout.addRow("Session Name:", name_edit)
        operator_edit = QLineEdit(load_app_setting("last_operator", ""))
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
        save_app_setting("last_operator", operator_edit.text())
        session_name_raw = name_edit.text().strip() or name_edit.placeholderText()
        session_name_safe = (
            "".join(
                c if c.isalnum() or c in (" ", "_", "-") else "_"
                for c in session_name_raw
            )
            .rstrip()
            .replace(" ", "_")
        )
        if not session_name_safe:
            session_name_safe = f"Session_Unnamed_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}"
        session_folder = os.path.join(PRIM_RESULTS_DIR, session_name_safe)
        try:
            os.makedirs(session_folder, exist_ok=True)
        except Exception as e:
            log.error(f"Fail create folder {session_folder}: {e}")
            QMessageBox.critical(self, "File Error", f"Folder error:\n{e}")
            return
        recording_base_prefix = os.path.join(session_folder, session_name_safe)
        self.last_trial_basepath = session_folder
        w, h = DEFAULT_FRAME_SIZE
        record_fps = DEFAULT_FPS
        if self.camera_thread and self.camera_settings:
            current_width = self.camera_settings.get("defaults", {}).get("Width")
            current_height = self.camera_settings.get("defaults", {}).get("Height")
            current_fps_setting = self.camera_settings.get("defaults", {}).get(
                "AcquisitionFrameRate"
            )
            if current_width and current_height:
                w, h = int(current_width), int(current_height)
                log.info(f"Using {w}x{h} from active cam settings.")
            if current_fps_setting:
                record_fps = float(current_fps_setting)
                log.info(f"Using FPS {record_fps} from active cam settings.")
        video_ext = DEFAULT_VIDEO_EXTENSION.lower()
        codec = DEFAULT_VIDEO_CODEC
        log.info(
            f"REC Start: '{session_name_safe}'. Params: FPS:{record_fps}, Size:{w}x{h}, Format:{video_ext}/{codec}"
        )
        try:
            if self._recording_worker and self._recording_worker.isRunning():
                self._recording_worker.stop_worker()
                self._recording_worker.wait(1000)
            if self._recording_worker:
                self._recording_worker.deleteLater()
            self._recording_worker = RecordingWorker(
                basepath=recording_base_prefix,
                fps=record_fps,
                frame_size=(w, h),
                video_ext=video_ext,
                video_codec=codec,
                parent=self,
            )
            self._recording_worker.start()
            QThread.msleep(300)
            if not (
                self._recording_worker
                and self._recording_worker.isRunning()
                and self._recording_worker.is_ready_to_record
            ):
                log.error("REC worker/TrialRecorder not ready.")
                raise RuntimeError("REC worker failed readiness.")
        except Exception as e:
            log.exception(f"Critical error REC start: {e}")
            QMessageBox.critical(self, "REC Error", f"Could not start REC worker: {e}")
            if self._recording_worker:
                self._recording_worker.deleteLater()
                self._recording_worker = None
                return
        self._is_recording = True
        if hasattr(self, "start_recording_action"):
            self.start_recording_action.setIcon(self.icon_recording_active)
        self._update_recording_actions_enable_state()
        if self.pressure_plot_widget:
            self.pressure_plot_widget.clear_plot()
        self.statusBar().showMessage(f"REC: {session_name_safe}", 0)

    def _trigger_stop_recording(self):
        if not self._is_recording or not self._recording_worker:
            log.info("Stop REC called, not active/no worker.")
            if self._is_recording:
                self._is_recording = False
            self._update_recording_actions_enable_state()
            if self.statusBar().currentMessage().startswith("REC:"):
                self.statusBar().clearMessage()
                return
        log.info("Stopping REC by user...")
        session_name_stopped = (
            os.path.basename(self.last_trial_basepath)
            if hasattr(self, "last_trial_basepath")
            else "Session"
        )
        try:
            self._recording_worker.stop_worker()
            if not self._recording_worker.wait(10000):
                log.warning("REC worker unresponsive. Terminating.")
                self._recording_worker.terminate()
                self._recording_worker.wait(1000)
            count = self._recording_worker.video_frame_count
            self.statusBar().showMessage(
                f"REC '{session_name_stopped}' stopped. {count} frames.", 7000
            )
            if hasattr(self, "last_trial_basepath") and self.last_trial_basepath:
                self._save_current_plot_data_for_session()
                reply = QMessageBox.information(
                    self,
                    "REC Saved",
                    f"Session '{session_name_stopped}' saved:\n{self.last_trial_basepath}\n\nOpen folder?",
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
            else:
                QMessageBox.information(
                    self, "REC Stopped", f"{count} frames recorded. Path info missing."
                )
        except Exception as e:
            log.exception(f"Error during user stop REC: {e}")
            self.statusBar().showMessage("Error stopping REC.", 5000)
        finally:
            if self._recording_worker:
                self._recording_worker.deleteLater()
            self._recording_worker = None
            self._is_recording = False
            if hasattr(self, "start_recording_action"):
                self.start_recording_action.setIcon(self.icon_record_start)
            self._update_recording_actions_enable_state()
            if self.statusBar().currentMessage().startswith("REC:"):
                self.statusBar().clearMessage()
            log.info("REC fully stopped and UI updated.")

    def _save_current_plot_data_for_session(self):
        if not hasattr(self, "last_trial_basepath") or not self.last_trial_basepath:
            log.warning("No last_trial_basepath for session plot.")
            return
        if not (self.pressure_plot_widget and self.pressure_plot_widget.times):
            log.info("No plot data for session.")
            return
        session_name = os.path.basename(self.last_trial_basepath)
        csv_filename = f"{session_name}_pressure_data.csv"
        csv_path = os.path.join(self.last_trial_basepath, csv_filename)
        try:
            with open(csv_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["time_s", "pressure_mmHg"])
                for t, p in zip(
                    self.pressure_plot_widget.times, self.pressure_plot_widget.pressures
                ):
                    writer.writerow([f"{t:.6f}", f"{p:.6f}"])
            log.info(f"Session plot auto-saved: {csv_path}")
            self.statusBar().showMessage(f"Plot CSV for '{session_name}' saved.", 4000)
        except Exception as e:
            log.exception(f"Fail auto-save session plot: {csv_path}: {e}")
            QMessageBox.warning(
                self, "Plot Save Error", f"Auto-save plot CSV error: {e}"
            )

    @pyqtSlot()
    def _clear_pressure_plot(self):
        if self.pressure_plot_widget:
            self.pressure_plot_widget.clear_plot()
            self.statusBar().showMessage("Plot cleared.", 3000)

    @pyqtSlot()
    def _export_plot_data_as_csv(self):
        if not (self.pressure_plot_widget and self.pressure_plot_widget.times):
            QMessageBox.information(self, "No Data", "Nothing to export.")
            return
        default_name = f"manual_plot_export_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Plot Data", default_name, "CSV Files (*.csv)"
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
                f"Plot data exported: {os.path.basename(path)}", 4000
            )
        except Exception as e:
            log.exception(f"Fail manual export plot: {e}")
            QMessageBox.critical(self, "Export Error", f"CSV save error: {e}")

    @pyqtSlot()
    def _show_about_dialog(self):
        app_name_for_dialog = (
            prim_app.APP_NAME if hasattr(prim_app, "APP_NAME") else "Application"
        )
        QMessageBox.about(self, f"About {app_name_for_dialog}", ABOUT_TEXT)

    def _update_app_session_time(self):
        self._app_session_seconds += 1
        h, rem = divmod(self._app_session_seconds, 3600)
        m, s = divmod(rem, 60)
        self.app_session_time_label.setText(f"Session: {h:02}:{m:02}:{s:02}")

    @pyqtSlot(str, str)
    def _on_camera_error(self, msg, code):
        full_msg = f"Camera Error: {msg}" + (f"\n(SDK Code: {code})" if code else "")
        log.error(full_msg)
        QMessageBox.critical(self, "Camera Runtime Error", full_msg)
        if self.camera_thread and self.camera_thread.isRunning():
            try:
                self.camera_thread.stop()
                self.camera_thread.wait(1000)
            except Exception as e:
                log.error(f"Error stopping cam thread post-error: {e}")
        if self.camera_panel:
            self.camera_panel.setEnabled(False)
        self.statusBar().showMessage("Camera Error! Stream stopped.", 0)

    def closeEvent(self, event):
        log.info("MainWindow closeEvent triggered.")
        if self._is_recording:
            reply = QMessageBox.question(
                self,
                "Confirm Exit",
                "REC active. Stop & exit?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                log.info("User chose stop REC & exit.")
                self._trigger_stop_recording()
            else:
                log.info("User cancelled exit during REC.")
                event.ignore()
                return

        thread_timeout = 1500
        threads_to_stop = [
            ("Camera", self.camera_thread, getattr(self.camera_thread, "stop", None)),
            ("Serial", self._serial_thread, getattr(self._serial_thread, "stop", None)),
            (
                "Recording",
                self._recording_worker,
                getattr(self._recording_worker, "stop_worker", None),
            ),
        ]
        for name, thread_instance, stop_method in threads_to_stop:
            if thread_instance:
                if thread_instance.isRunning() and stop_method:
                    log.info(f"Stopping {name} thread on close...")
                    stop_method()
                    if not thread_instance.wait(
                        thread_timeout + (2000 if name == "Recording" else 0)
                    ):  # Extra for recording
                        log.warning(f"{name} thread unresponsive, terminating.")
                        thread_instance.terminate()
                        thread_instance.wait(500)  # wait after terminate
                thread_instance.deleteLater()
                if name == "Camera":
                    self.camera_thread = None
                elif name == "Serial":
                    self._serial_thread = None
                elif name == "Recording":
                    self._recording_worker = None

        log.info("All threads processed. Proceeding with app close.")
        super().closeEvent(event)
