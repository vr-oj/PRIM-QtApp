# PRIM-QTAPP/prim_app/main_window.py
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
)
from PyQt5.QtCore import Qt, pyqtSlot, QTimer, QVariant, QDateTime, QSize
from PyQt5.QtGui import QIcon, QKeySequence

import prim_app
from prim_app import initialize_ic4_with_cti, is_ic4_fully_initialized
import imagingcontrol4 as ic4  # Ensured import

from utils.app_settings import (
    save_app_setting,
    load_app_setting,
    SETTING_CTI_PATH,
    SETTING_LAST_CAMERA_SERIAL,
    # SETTING_LAST_PROFILE_NAME, # Commented out as we shift to auto-detection
)
from utils.config import (
    # CAMERA_PROFILES_DIR, # Commented out
    DEFAULT_FPS,
    DEFAULT_FRAME_SIZE,
    APP_NAME,  # Used this instead of prim_app.APP_NAME for consistency
    APP_VERSION,  # Used this instead of prim_app.CONFIG_APP_VERSION
    PRIM_RESULTS_DIR,
    DEFAULT_VIDEO_EXTENSION,
    DEFAULT_VIDEO_CODEC,
    ABOUT_TEXT,
    CAMERA_HARDCODED_DEFAULTS,  # Import the new hardcoded defaults
)

from ui.control_panels.top_control_panel import TopControlPanel
from ui.control_panels.camera_control_panel import CameraControlPanel
from ui.canvas.gl_viewfinder import GLViewfinder
from ui.canvas.pressure_plot_widget import PressurePlotWidget
from threads.sdk_camera_thread import (
    SDKCameraThread,
)  # Assumed this is the corrected version
from camera.setup_wizard import CameraSetupWizard
from threads.serial_thread import SerialThread
from recording import RecordingWorker
from utils.utils import list_serial_ports

log = logging.getLogger(__name__)


# Consider moving snake_case to utils.py if used in multiple files
def snake_case(name: str) -> str:
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).upper()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._serial_thread = None
        self._recording_worker = None
        self._is_recording = False
        self.camera_thread = None
        self.camera_panel = None  # Initialized in _build_central_widget_layout
        self.camera_view = None  # Initialized in _build_central_widget_layout
        self.bottom_split = None  # Initialized in _build_central_widget_layout
        self.camera_settings = {}

        self._init_paths_and_icons()
        self._build_console_log_dock()
        self._build_central_widget_layout()  # Now self.camera_panel is created
        self._build_menus()
        self._build_main_toolbar()
        self._build_status_bar()

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
            f"{APP_NAME} - v{APP_VERSION}"  # Using imported config values
        )

        self._check_and_prompt_for_cti_on_startup()
        if is_ic4_fully_initialized():
            QTimer.singleShot(0, self._initialize_camera_on_startup)
        else:
            self.statusBar().showMessage(
                "IC4 SDK not fully configured. Use Camera > Setup...", 5000
            )
            if self.camera_panel:
                self.camera_panel.setEnabled(False)

        self.showMaximized()
        QTimer.singleShot(50, self._set_initial_splitter_sizes)
        self._set_initial_control_states()  # Call after UI is built
        log.info("MainWindow initialized.")

    def _set_initial_splitter_sizes(self):
        if self.bottom_split:
            w = self.bottom_split.width()
            if w > 0:  # Ensure width is positive
                # Adjust as per your layout preference. This assumes 2 main panels in bottom_split.
                self.bottom_split.setSizes([int(w * 0.6), int(w * 0.4)])

    def _check_and_prompt_for_cti_on_startup(self):
        # Your existing logic here is good.
        if not is_ic4_fully_initialized() and prim_app.IC4_AVAILABLE:
            QMessageBox.information(
                self,
                "Camera SDK Setup Required",
                "Select the GenTL Producer file (.cti) for your camera.",
            )
            cti_dir = os.path.dirname(load_app_setting(SETTING_CTI_PATH, "")) or ""
            cti, _ = QFileDialog.getOpenFileName(
                self, "Select .cti", cti_dir, "CTI Files (*.cti)"
            )
            if cti and os.path.exists(cti):
                try:
                    initialize_ic4_with_cti(cti)
                    save_app_setting(SETTING_CTI_PATH, cti)
                    QMessageBox.information(
                        self, "CTI Loaded", f"Loaded: {os.path.basename(cti)}"
                    )
                    self.statusBar().showMessage(f"CTI: {os.path.basename(cti)}", 5000)
                except Exception as e:
                    QMessageBox.critical(self, "CTI Error", str(e))
            else:
                self.statusBar().showMessage(
                    "No CTI file selected. Camera functionality will be limited.", 5000
                )
                if self.camera_panel:  # Check if camera_panel exists
                    self.camera_panel.setEnabled(False)
        elif is_ic4_fully_initialized():
            self.statusBar().showMessage(
                f"IC4 initialized with CTI: {os.path.basename(load_app_setting(SETTING_CTI_PATH, ''))}",
                5000,
            )

    def _connect_camera_signals(self):
        th = self.camera_thread
        cp = self.camera_panel
        if not (th and cp and self.camera_view):
            log.warning(
                "Cannot connect camera signals: thread, panel, or view missing."
            )
            return True

        # Robust disconnection of any previous signals
        # Store connections made to disconnect them specifically if needed,
        # though Qt usually handles this if objects are parented or deleted.
        # For simplicity, direct connect/disconnect or rely on Qt's auto-disconnect on object deletion.
        # Your previous version's disconnect loop was fine, but let's ensure we're connecting to current instances.

        # Disconnect all previous connections from signals to avoid multiple calls (idempotency)
        try:
            th.resolutions_updated.disconnect()
        except TypeError:
            pass
        try:
            th.pixel_formats_updated.disconnect()
        except TypeError:
            pass
        try:
            th.fps_range_updated.disconnect()
        except TypeError:
            pass
        try:
            th.exposure_range_updated.disconnect()
        except TypeError:
            pass
        try:
            th.gain_range_updated.disconnect()
        except TypeError:
            pass
        try:
            th.auto_exposure_updated.disconnect()
        except TypeError:
            pass
        try:
            th.properties_updated.disconnect()
        except TypeError:
            pass
        try:
            th.frame_ready.disconnect()
        except TypeError:
            pass
        try:
            th.camera_error.disconnect()
        except TypeError:
            pass

        try:
            cp.resolution_changed.disconnect()
        except TypeError:
            pass
        try:
            cp.pixel_format_changed.disconnect()
        except TypeError:
            pass
        try:
            cp.auto_exposure_toggled.disconnect()
        except TypeError:
            pass
        try:
            cp.exposure_changed.disconnect()
        except TypeError:
            pass
        try:
            cp.gain_changed.disconnect()
        except TypeError:
            pass
        try:
            cp.fps_changed.disconnect()
        except TypeError:
            pass
        try:
            cp.start_stream.disconnect()
        except TypeError:
            pass
        try:
            cp.stop_stream.disconnect()
        except TypeError:
            pass

        # Thread → Panel
        th.resolutions_updated.connect(
            lambda r: cp.res_combo.clear() or cp.res_combo.addItems(r or [])
        )
        th.pixel_formats_updated.connect(
            lambda f: cp.pix_combo.clear() or cp.pix_combo.addItems(f or [])
        )
        th.fps_range_updated.connect(lambda lo, hi: cp.fps_spin.setRange(lo, hi))
        th.exposure_range_updated.connect(lambda lo, hi: cp.exp_spin.setRange(lo, hi))
        th.gain_range_updated.connect(
            lambda lo, hi: cp.gain_slider.setRange(int(lo), int(hi))
        )
        th.auto_exposure_updated.connect(cp.auto_exp_cb.setChecked)

        def update_panel_from_props(props_dict):
            # SDKCameraThread emits dict with UPPER_SNAKE_CASE keys like "EXPOSURE_TIME"
            # CameraControlPanel widgets should be updated accordingly.
            if "EXPOSURE_TIME" in props_dict:
                cp.exp_spin.setValue(props_dict["EXPOSURE_TIME"])
            if "GAIN" in props_dict:
                cp.gain_slider.setValue(int(props_dict["GAIN"]))
            if "ACQUISITION_FRAME_RATE" in props_dict:
                cp.fps_spin.setValue(props_dict["ACQUISITION_FRAME_RATE"])
            # Update pixel format combo if PIXEL_FORMAT string is in props_dict
            if "PIXEL_FORMAT" in props_dict:
                idx = cp.pix_combo.findText(
                    props_dict["PIXEL_FORMAT"], Qt.MatchFixedString
                )
                if idx >= 0:
                    cp.pix_combo.setCurrentIndex(idx)
            # Update resolution (Width/Height) if they are separate items in panel, or a combined string
            # This part depends on how CameraControlPanel handles resolution display.
            # Assuming for now it's handled by direct Width/Height properties if needed.

        th.properties_updated.connect(update_panel_from_props)

        # Panel → Thread
        # CameraControlPanel emits values that SDKCameraThread.apply_node_settings expects (CamelCase keys)
        cp.resolution_changed.connect(
            lambda r: r
            and th.apply_node_settings(
                {"Width": int(r.split("x")[0]), "Height": int(r.split("x")[1])}
            )
        )
        cp.pixel_format_changed.connect(
            lambda f: th.apply_node_settings({"PixelFormat": f})
        )
        cp.auto_exposure_toggled.connect(
            lambda on: th.apply_node_settings(
                {"ExposureAuto": "Continuous" if on else "Off"}
            )
        )
        cp.exposure_changed.connect(
            lambda v: th.apply_node_settings({"ExposureTime": v})
        )
        cp.gain_changed.connect(lambda v: th.apply_node_settings({"Gain": v}))
        cp.fps_changed.connect(
            lambda v: th.apply_node_settings({"AcquisitionFrameRate": v})
        )

        cp.start_stream.connect(th.start)
        cp.stop_stream.connect(th.stop)

        th.frame_ready.connect(self.camera_view.update_frame)
        th.camera_error.connect(self._on_camera_error)

        log.info("Camera signals connected.")
        return False  # Indicates success

    def _start_sdk_camera_thread(self, camera_identifier, fps, initial_settings=None):
        if self.camera_thread and self.camera_thread.isRunning():
            log.info("Stopping existing camera thread before starting new one.")
            self.camera_thread.stop()
            self.camera_thread.deleteLater()
            self.camera_thread = None
            QApplication.processEvents()

        log.info(
            f"Creating SDKCameraThread for device: '{camera_identifier}', Target FPS: {fps}"
        )
        self.camera_thread = SDKCameraThread(
            device_name=camera_identifier, fps=float(fps), parent=self
        )

        # self.camera_settings is already populated by _initialize_camera_on_startup
        # Update the 'cameraSerialPattern' which SDKCameraThread might use internally if 'device_name' isn't serial
        self.camera_settings["cameraSerialPattern"] = camera_identifier

        if self._connect_camera_signals():
            log.error("Failed to connect camera signals for new SDKCameraThread.")
            self.camera_thread.deleteLater()
            self.camera_thread = None
            if self.camera_panel:
                self.camera_panel.setEnabled(False)
            return

        if initial_settings:
            log.debug(
                f"Queuing application of initial hardcoded settings: {initial_settings}"
            )

            def apply_initial_settings_on_thread():
                if self.camera_thread and self.camera_thread.pm:
                    log.info(
                        f"Applying initial hardcoded settings via QTimer: {initial_settings}"
                    )
                    self.camera_thread.apply_node_settings(
                        initial_settings
                    )  # Assumes initial_settings keys are CamelCase
                elif self.camera_thread:
                    log.warning(
                        "apply_initial_settings_on_thread: pm not ready, retrying..."
                    )
                    QTimer.singleShot(300, apply_initial_settings_on_thread)
                else:
                    log.warning(
                        "apply_initial_settings_on_thread: camera_thread is None"
                    )

            # Increased delay to allow SDKCameraThread.run() to open device and init self.pm
            QTimer.singleShot(700, apply_initial_settings_on_thread)

        log.info(f"Starting SDKCameraThread for {camera_identifier}...")
        self.camera_thread.start()
        # UI panel enabling and status messages will be handled based on thread signals (e.g. successful init or error)
        # For now, optimistically enable and set status.
        # SDKCameraThread should emit signals that MainWindow can use to update UI precisely.
        if self.camera_panel:
            self.camera_panel.setEnabled(True)
        current_model_display = self.camera_settings.get(
            "cameraModel", camera_identifier
        )
        self.statusBar().showMessage(
            f"Attempting to start camera: {current_model_display}", 5000
        )

    def _initialize_camera_on_startup(self):  # Renamed from _try_load_last_camera
        if not is_ic4_fully_initialized():
            log.info("IC4 not fully initialized, cannot auto-configure camera.")
            self.statusBar().showMessage(
                "IC4 SDK not configured. Use Camera > Setup...", 5000
            )
            if self.camera_panel:
                self.camera_panel.setEnabled(False)
            return

        log.info("Attempting to auto-detect and configure known lab cameras...")

        available_devices = []
        try:
            available_devices = ic4.DeviceEnum.devices()
            if not available_devices:
                log.warning("No camera devices found by ic4.DeviceEnum.")
                self.statusBar().showMessage("No camera devices found.", 5000)
                if self.camera_panel:
                    self.camera_panel.setEnabled(False)
                return
        except Exception as e:
            log.error(
                f"Error enumerating IC4 devices: {e}"
            )  # Catch specific ic4 exceptions if possible
            self.statusBar().showMessage(f"Error enumerating devices: {e}", 5000)
            if self.camera_panel:
                self.camera_panel.setEnabled(False)
            return

        detected_camera_device_info = None
        camera_model_name_found = None

        for dev_info in available_devices:
            model_name = dev_info.model_name
            log.debug(
                f"Found device: Model='{model_name}', Serial='{dev_info.serial_number}', ID='{dev_info.unique_id}'"
            )
            if model_name in CAMERA_HARDCODED_DEFAULTS:
                log.info(
                    f"Known lab camera detected: {model_name} (SN: {dev_info.serial_number})"
                )
                detected_camera_device_info = dev_info
                camera_model_name_found = model_name
                break  # Use the first known camera found

        if not detected_camera_device_info:
            models_found = [d.model_name for d in available_devices]
            serials_found = [d.serial_number for d in available_devices]
            log.warning(
                f"No known lab cameras found. Connected devices models: {models_found}, serials: {serials_found}"
            )
            self.statusBar().showMessage("No supported lab camera detected.", 7000)
            if self.camera_panel:
                self.camera_panel.setEnabled(False)
            return

        if (
            camera_model_name_found
            and camera_model_name_found in CAMERA_HARDCODED_DEFAULTS
        ):
            hardcoded_settings = CAMERA_HARDCODED_DEFAULTS[
                camera_model_name_found
            ].copy()  # Use a copy
            log.info(
                f"Loading hardcoded default settings for {camera_model_name_found}: {hardcoded_settings}"
            )

            target_fps = float(
                hardcoded_settings.get("AcquisitionFrameRate", DEFAULT_FPS)
            )

            camera_identifier = detected_camera_device_info.serial_number
            if not camera_identifier:
                camera_identifier = detected_camera_device_info.unique_id
                log.warning(
                    f"Serial for {camera_model_name_found} empty. Using Unique ID: {camera_identifier}"
                )
            if not camera_identifier:
                camera_identifier = camera_model_name_found
                log.warning(
                    f"Unique ID for {camera_model_name_found} empty. Using Model: {camera_identifier} (less robust)."
                )

            self.camera_settings = {
                "cameraModel": camera_model_name_found,
                "cameraSerialPattern": camera_identifier,
                "defaults": hardcoded_settings,  # For reference, SDKCameraThread gets flat dict
                "source": "hardcoded_default",
            }

            try:
                self._start_sdk_camera_thread(
                    camera_identifier, target_fps, hardcoded_settings
                )
                save_app_setting(SETTING_LAST_CAMERA_SERIAL, camera_identifier)
            except Exception as e:
                log.exception(
                    f"Failed to start camera '{camera_model_name_found}' with hardcoded settings: {e}"
                )
                QMessageBox.critical(
                    self,
                    "Camera Start Error",
                    f"Could not start {camera_model_name_found}:\n{e}",
                )
                if self.camera_panel:
                    self.camera_panel.setEnabled(False)
        else:  # Should not happen if detected_camera_device_info is set
            log.error(
                "Logic error: Detected camera but couldn't find its hardcoded settings."
            )
            if self.camera_panel:
                self.camera_panel.setEnabled(False)

    def _run_camera_setup(self):
        if not is_ic4_fully_initialized():
            QMessageBox.warning(
                self,
                "Camera SDK Not Ready",
                "IC4 SDK not configured. Use 'Camera > Change CTI File...' first.",
            )
            return

        if self.camera_thread and self.camera_thread.isRunning():
            log.info("Stopping existing camera thread before running setup wizard...")
            self.camera_thread.stop()
            self.camera_thread.deleteLater()
            self.camera_thread = None
            if self.camera_panel:
                self.camera_panel.setEnabled(False)
            QApplication.processEvents()
            log.info("Existing camera thread stopped for setup wizard.")

        wizard = CameraSetupWizard(self)
        if wizard.exec_() != QDialog.Accepted:
            log.info("Camera Setup Wizard cancelled.")
            # Optionally, try to restart the previously auto-detected camera if self.camera_settings is still valid
            # For now, if cancelled, camera remains off until app restart or manual action.
            return

        self.camera_settings = wizard.settings
        log.info(
            f"Camera Setup Wizard completed. Settings: {list(self.camera_settings.keys())}"
        )

        # Save profile from wizard if you want to enable profiles again later
        profile_name_saved_as = self.camera_settings.get("profileNameSavedAs")
        camera_serial_from_wizard = self.camera_settings.get("cameraSerialPattern")

        # if profile_name_saved_as:
        #     save_app_setting(SETTING_LAST_PROFILE_NAME, profile_name_saved_as) # Re-enable if using profiles
        if camera_serial_from_wizard:
            save_app_setting(SETTING_LAST_CAMERA_SERIAL, camera_serial_from_wizard)

        all_wizard_settings = {
            **self.camera_settings.get("defaults", {}),
            **self.camera_settings.get("advanced", {}),
        }
        target_fps_from_wizard = float(
            all_wizard_settings.get("AcquisitionFrameRate", DEFAULT_FPS)
        )

        if camera_serial_from_wizard:
            log.info(
                f"Starting camera from wizard settings for SN/Pattern: {camera_serial_from_wizard}"
            )
            self._start_sdk_camera_thread(
                camera_serial_from_wizard, target_fps_from_wizard, all_wizard_settings
            )
        else:
            log.error("No camera serial in wizard settings.")
            QMessageBox.critical(self, "Setup Error", "No camera serial from wizard.")

    def _init_paths_and_icons(self):
        # Your existing code seems fine.
        base = os.path.dirname(os.path.abspath(__file__))
        icon_dir = os.path.join(base, "ui", "icons")
        if not os.path.isdir(icon_dir):
            alt_icon_dir = os.path.join(
                os.path.dirname(base), "ui", "icons"
            )  # For dev structure
            if os.path.isdir(alt_icon_dir):
                icon_dir = alt_icon_dir
            else:
                log.warning(f"Icon directory not found at {icon_dir} or {alt_icon_dir}")

        def get_icon(name):
            path = os.path.join(icon_dir, name)
            return QIcon(path) if os.path.exists(path) else QIcon()

        self.icon_record_start = get_icon("record.svg")
        self.icon_record_stop = get_icon("stop.svg")
        self.icon_recording_active = get_icon("recording_active.svg")
        self.icon_connect = get_icon("plug.svg")
        self.icon_disconnect = get_icon("plug_disconnect.svg")

    def _build_console_log_dock(self):
        # Your existing code seems fine.
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
        # Your existing code seems fine.
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(3)
        top_row = QWidget()
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(5)
        self.camera_panel = CameraControlPanel(self)  # Panel created here
        top_layout.addWidget(self.camera_panel)
        # self.camera_panel.setEnabled(False) # Initial state set in _set_initial_control_states
        self.top_ctrl = TopControlPanel(self)
        top_layout.addWidget(self.top_ctrl)
        if hasattr(self.top_ctrl, "plot_controls"):
            top_layout.addWidget(self.top_ctrl.plot_controls)
        else:
            log.error(
                "self.top_ctrl.plot_controls not found."
            )  # Should not happen if TopControlPanel is correct
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
        # Your existing code seems fine.
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
        about_act = QAction(
            f"&About {APP_NAME}", self, triggered=self._show_about_dialog
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
        # Your existing code seems fine.
        cti_path, _ = QFileDialog.getOpenFileName(self, "Select CTI File", "", "*.cti")
        if not cti_path:
            return
        try:
            initialize_ic4_with_cti(cti_path)  # from prim_app
            QMessageBox.information(self, "CTI Loaded", f"Loaded CTI:\n{cti_path}")
            # Consider restarting camera detection or prompting user
            self._initialize_camera_on_startup()  # Re-try camera init with new CTI
        except Exception as exc:
            QMessageBox.critical(self, "CTI Exception", str(exc))

    def _build_main_toolbar(self):
        # Your existing code seems fine.
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
            "🔌 Simulated Data", QVariant()
        )  # QVariant for consistency
        ports = list_serial_ports()  # from utils.utils
        if ports:
            for p_dev, p_desc in ports:  # Unpack tuple
                self.serial_port_combobox.addItem(
                    f"{os.path.basename(p_dev)} ({p_desc})", QVariant(p_dev)
                )
        else:
            self.serial_port_combobox.addItem(
                "No Serial Ports Found", QVariant()
            )  # Use QVariant() for no port
            self.serial_port_combobox.setEnabled(False)
        tb.addWidget(self.serial_port_combobox)
        tb.addSeparator()
        if hasattr(self, "start_recording_action"):
            tb.addAction(self.start_recording_action)
        if hasattr(self, "stop_recording_action"):
            tb.addAction(self.stop_recording_action)

    def _build_status_bar(self):
        # Your existing code seems fine.
        sb = self.statusBar()  # Gets existing or creates one if None
        self.setStatusBar(sb)  # Ensure it's set
        self.app_session_time_label = QLabel("Session: 00:00:00")
        sb.addPermanentWidget(self.app_session_time_label)
        self._app_session_seconds = 0
        self._app_session_timer = QTimer(self)  # Parent `self` is good
        self._app_session_timer.setInterval(1000)  # Set interval explicitly
        self._app_session_timer.timeout.connect(self._update_app_session_time)
        self._app_session_timer.start()

    def _set_initial_control_states(self):
        if self.top_ctrl:
            self.top_ctrl.update_connection_status("Disconnected", False)
        if hasattr(self, "start_recording_action"):
            self.start_recording_action.setEnabled(False)
        if hasattr(self, "stop_recording_action"):
            self.stop_recording_action.setEnabled(False)

        # Camera panel is now enabled/disabled by camera start/stop logic
        if self.camera_panel:
            self.camera_panel.setEnabled(False)

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

    # --- Recording Methods ---
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
        os.makedirs(session_folder, exist_ok=True)
        recording_base_prefix = os.path.join(session_folder, session_name_safe)
        self.last_trial_basepath = session_folder

        w, h = DEFAULT_FRAME_SIZE
        record_fps = DEFAULT_FPS
        active_cam_settings = self.camera_settings.get(
            "defaults", {}
        )  # 'defaults' holds the hardcoded set

        queried_live = False
        if self.camera_thread and self.camera_thread.pm:
            try:
                # Ensure PropId attributes are correctly accessed (assuming _propid_map is working in SDKCameraThread)
                # For direct access here, we'd need to know if ic4.PropId.WIDTH etc. are valid.
                # It's safer if SDKCameraThread stores these current values after setting or querying.
                # Let's assume self.camera_settings["defaults"] has the applied Width/Height/FPS.
                # If not, SDKCameraThread should emit them via properties_updated.

                # Simplified: use stored settings from self.camera_settings which were applied.
                # More robust would be to have SDKCameraThread maintain current W,H,FPS properties.
                current_width = active_cam_settings.get("Width")
                current_height = active_cam_settings.get("Height")
                current_fps_setting = active_cam_settings.get("AcquisitionFrameRate")
                if current_width and current_height:
                    w, h = int(current_width), int(current_height)
                if current_fps_setting:
                    record_fps = float(current_fps_setting)
                log.info(
                    f"Using stored/hardcoded settings for recording: W={w}, H={h}, FPS={record_fps}"
                )
                queried_live = True  # Placeholder, as this is not truly live query here
            except Exception as e_live_query:
                log.warning(
                    f"Could not use settings from self.camera_settings for recording, falling back: {e_live_query}"
                )

        if (
            not queried_live
        ):  # Fallback if settings not found in self.camera_settings.defaults
            log.warning(
                f"No camera settings in self.camera_settings.defaults, using general defaults for recording: W={w}, H={h}, FPS={record_fps}"
            )

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
                raise RuntimeError("REC worker failed readiness.")
            self._is_recording = True
            self.start_recording_action.setIcon(self.icon_recording_active)
            self._update_recording_actions_enable_state()
            self.pressure_plot_widget.clear_plot()
            self.statusBar().showMessage(f"REC: {session_name_safe}", 0)
        except Exception as e:
            log.exception("Critical error REC start")
            QMessageBox.critical(self, "REC Error", f"Could not start REC: {e}")
            self._is_recording = False
            self._update_recording_actions_enable_state()
            return

    def _trigger_stop_recording(self):
        # Your existing code seems mostly fine.
        if not self._is_recording or not self._recording_worker:
            log.info("Stop REC called, not active/no worker.")
            self._is_recording = False
            self._update_recording_actions_enable_state()
            (
                self.statusBar().clearMessage()
                if self.statusBar().currentMessage().startswith("REC:")
                else None
            )
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
                log.warning("REC worker unresponsive, terminating.")
                self._recording_worker.terminate()
                self._recording_worker.wait(1000)
            count = self._recording_worker.video_frame_count
            self.statusBar().showMessage(
                f"REC '{session_name_stopped}' stopped. {count} frames.", 7000
            )
            if hasattr(self, "last_trial_basepath") and self.last_trial_basepath:
                self._save_current_plot_data_for_session()
                if (
                    QMessageBox.information(
                        self,
                        "REC Saved",
                        f"Session '{session_name_stopped}' saved:\n{self.last_trial_basepath}\n\nOpen folder?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No,
                    )
                    == QMessageBox.Yes
                ):
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
            log.exception("Error during user stop REC")
            self.statusBar().showMessage("Error stopping REC.", 5000)
        finally:
            self._recording_worker.deleteLater() if self._recording_worker else None
            self._recording_worker = None
            self._is_recording = False
            (
                self.start_recording_action.setIcon(self.icon_record_start)
                if hasattr(self, "start_recording_action")
                else None
            )
            self._update_recording_actions_enable_state()
            (
                self.statusBar().clearMessage()
                if self.statusBar().currentMessage().startswith("REC:")
                else None
            )
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

        if self.camera_thread:
            if self.camera_thread.isRunning():
                try:
                    log.info("Stopping camera thread due to error...")
                    self.camera_thread.stop()
                except Exception as e_stop:
                    log.error(f"Error stopping camera thread post-error: {e_stop}")
            self.camera_thread.deleteLater()
            self.camera_thread = None

        if self.camera_panel:
            self.camera_panel.setEnabled(False)
        self.statusBar().showMessage(
            "Camera Error! Stream stopped or failed to start.", 0
        )

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

        # Orderly shutdown of threads
        threads_to_clean = [
            (
                "Camera",
                "_camera_thread",
                (
                    getattr(self.camera_thread, "stop", None)
                    if self.camera_thread
                    else None
                ),
            ),
            (
                "Serial",
                "_serial_thread",
                (
                    getattr(self._serial_thread, "stop", None)
                    if self._serial_thread
                    else None
                ),
            ),
            (
                "Recording",
                "_recording_worker",
                (
                    getattr(self._recording_worker, "stop_worker", None)
                    if self._recording_worker
                    else None
                ),
            ),
        ]

        for name, attr_name, stop_method in threads_to_clean:
            thread_instance = getattr(self, attr_name, None)
            if thread_instance:
                if thread_instance.isRunning() and stop_method:
                    log.info(f"Stopping {name} thread on close...")
                    stop_method()  # Call the specific stop method
                    # Adjust wait timeout as needed
                    wait_timeout = 3000 if name == "Recording" else 1500
                    if not thread_instance.wait(wait_timeout):
                        log.warning(f"{name} thread unresponsive, terminating.")
                        thread_instance.terminate()
                        thread_instance.wait(500)
                thread_instance.deleteLater()
                setattr(self, attr_name, None)  # Clear the attribute

        log.info("All threads processed. Proceeding with app close.")
        super().closeEvent(event)
