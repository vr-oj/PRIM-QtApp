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
    QHBoxLayout,
    QWidget,
    QSplitter,
    QSizePolicy,
    QMessageBox,
)
from PyQt5.QtCore import Qt, pyqtSlot, QTimer, QVariant, QDateTime, QSize, QThread
from PyQt5.QtGui import QIcon, QKeySequence

# Updated imports:
# Assuming prim_app.py might be in a directory structure that allows this import style
# If prim_app.py is in the same directory, it would be: from prim_app import ...
# For robust module access, ensure prim_app (the module) is correctly on PYTHONPATH
# or adjust relative import. For now, assuming direct import works if in same package.
import prim_app  # To access its global flags like IC4_INITIALIZED

from prim_app import initialize_ic4_with_cti, IC4_INITIALIZED, IC4_AVAILABLE
from utils.app_settings import (
    save_app_setting,
    load_app_setting,
    SETTING_CTI_PATH,
    SETTING_LAST_CAMERA_SERIAL,
    SETTING_LAST_PROFILE_NAME,
)
from utils.config import (
    CAMERA_PROFILES_DIR,  # For loading profiles
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
        self.camera_settings = (
            {}
        )  # Store current camera settings from wizard or profile

        self._init_paths_and_icons()
        self._build_console_log_dock()
        self._build_central_widget_layout()
        self._build_menus()
        self._build_main_toolbar()
        self._build_status_bar()

        # Connect plot controls
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

        self.setWindowTitle(f"{APP_NAME} - v{APP_VERSION or '1.0'}")

        # Initial CTI check and prompt if necessary
        # This uses the global IC4_INITIALIZED flag from prim_app module
        self._check_and_prompt_for_cti_on_startup()

        # Attempt to auto-load and start the last used camera
        # This should run after CTI is potentially loaded by _check_and_prompt_for_cti_on_startup
        if prim_app.IC4_INITIALIZED:  # Check the flag from prim_app module
            QTimer.singleShot(
                0, self._try_load_last_camera
            )  # Use QTimer to run after main window setup
        else:
            log.info("IC4 not initialized, skipping auto-load of last camera.")
            self.statusBar().showMessage(
                "IC4 SDK not initialized. Camera features require CTI setup.", 5000
            )

        self.showMaximized()
        QTimer.singleShot(0, self._set_initial_splitter_sizes)
        self._set_initial_control_states()
        log.info("MainWindow initialized.")

    def _check_and_prompt_for_cti_on_startup(self):
        """
        Checks if IC4 is initialized. If not, and IC4 is available,
        prompts the user to select a CTI file.
        This is called during MainWindow initialization.
        """
        # Use the global IC4_INITIALIZED from prim_app
        if not prim_app.IC4_INITIALIZED and prim_app.IC4_AVAILABLE:
            log.info(
                "IC4 SDK is available but not initialized. Prompting for CTI file."
            )
            QMessageBox.information(
                self,
                "Camera SDK Setup",
                "The IC Imaging Control SDK needs a GenTL Producer file (.cti) to work with your camera(s).\n\nPlease select the .cti file for your camera hardware.",
            )

            # Suggest starting directory based on last saved CTI path, if any
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
                    # This function from prim_app will update prim_app.IC4_INITIALIZED
                    initialize_ic4_with_cti(cti_path)
                    if prim_app.IC4_INITIALIZED:  # Check updated global flag
                        save_app_setting(SETTING_CTI_PATH, cti_path)
                        QMessageBox.information(
                            self,
                            "CTI Loaded",
                            f"GenTL Producer loaded successfully: {os.path.basename(cti_path)}\n"
                            "You can now use 'Camera > Setup Camera...' to configure your camera.",
                        )
                        self.statusBar().showMessage(
                            f"CTI loaded: {os.path.basename(cti_path)}", 5000
                        )
                    else:  # initialize_ic4_with_cti failed internally
                        QMessageBox.critical(
                            self,
                            "CTI Load Error",
                            f"Failed to initialize the camera SDK with: {os.path.basename(cti_path)}.\n"
                            "Please ensure it's the correct file for your camera and SDK version.",
                        )
                except Exception as e:
                    QMessageBox.critical(
                        self,
                        "CTI Exception",
                        f"An error occurred while trying to load {os.path.basename(cti_path)}: {e}",
                    )
                    log.exception(
                        f"Exception initializing CTI '{cti_path}' via prompt."
                    )
            elif cti_path:
                QMessageBox.warning(
                    self,
                    "File Not Found",
                    f"The selected CTI file was not found: {cti_path}",
                )
            else:
                QMessageBox.warning(
                    self,
                    "CTI Not Selected",
                    "No CTI file was selected. Camera functionality will be limited until a CTI is configured via 'Camera > Setup Camera...'.",
                )
        elif prim_app.IC4_INITIALIZED:
            log.info(
                "IC4 already initialized (likely from saved settings). Skipping startup CTI prompt."
            )
            self.statusBar().showMessage(
                f"IC4 initialized with CTI: {os.path.basename(load_app_setting(SETTING_CTI_PATH, 'Unknown CTI'))}",
                5000,
            )
        elif not prim_app.IC4_AVAILABLE and not os.environ.get(
            "PRIM_APP_TESTING_NO_IC4"
        ):  # Only if not testing without it
            log.warning(
                "IC4_AVAILABLE is false (imagingcontrol4 module likely missing). Camera features disabled."
            )

    def _connect_camera_signals(self):
        """Helper method to connect signals between camera thread, panel, and view."""
        if not self.camera_thread:
            log.error("Camera thread not available to connect signals.")
            return True  # Indicate an issue
        if not self.camera_panel:
            log.error("Camera panel not available to connect signals.")
            return True
        if not self.camera_view:
            log.error("Camera view not available to connect signals.")
            return True

        th = self.camera_thread
        cp = self.camera_panel

        # Disconnect all previous connections to avoid duplicates if called multiple times
        # This is a bit aggressive but ensures clean state.
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
                try:
                    signal = getattr(widget, signal_name)
                    # Attempt to disconnect all slots. This might not work perfectly for all signals
                    # or might throw errors if no connections exist.
                    # A more robust way is to disconnect specific slots if they are known.
                    while (
                        True
                    ):  # Keep trying to disconnect until it fails (meaning no more connections)
                        signal.disconnect()
                except (
                    TypeError,
                    RuntimeError,
                ):  # TypeError if no connections, RuntimeError for some cases
                    pass  # No connections to disconnect for this signal/widget combination

        try:
            th.resolutions_updated.disconnect()
            th.pixel_formats_updated.disconnect()
            th.fps_range_updated.disconnect()
            th.exposure_range_updated.disconnect()
            th.gain_range_updated.disconnect()
            th.auto_exposure_updated.disconnect()
            th.properties_updated.disconnect()
            th.frame_ready.disconnect()
            th.camera_error.disconnect()
        except TypeError:
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

        th.fps_range_updated.connect(
            lambda lo, hi: (
                cp.fps_spin.setRange(lo, hi),
                cp.fps_spin.setValue(
                    self.camera_settings.get("defaults", {}).get(
                        "AcquisitionFrameRate", DEFAULT_FPS
                    )
                ),
            )
        )
        th.exposure_range_updated.connect(
            lambda lo, hi: (
                cp.exp_spin.setRange(lo, hi),
                cp.exp_spin.setValue(
                    self.camera_settings.get("defaults", {}).get("ExposureTime", lo)
                ),
            )
        )
        th.gain_range_updated.connect(
            lambda lo, hi: (
                cp.gain_slider.setRange(int(lo), int(hi)),
                cp.gain_slider.setValue(
                    int(self.camera_settings.get("defaults", {}).get("Gain", int(lo)))
                ),
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
        return False  # No issue

    def _start_sdk_camera_thread(self, camera_serial, fps, initial_settings=None):
        """Helper to stop old thread, create, connect, and start new SDKCameraThread."""
        if self.camera_thread and self.camera_thread.isRunning():
            log.info("Stopping existing camera thread...")
            self.camera_thread.stop()
            if not self.camera_thread.wait(2000):
                log.warning("Camera thread did not stop gracefully, terminating.")
                self.camera_thread.terminate()
                self.camera_thread.wait(500)
        self.camera_thread = None

        log.info(
            f"Initializing SDKCameraThread for device: {camera_serial} at {fps} FPS"
        )
        self.camera_thread = SDKCameraThread(
            device_name=camera_serial, fps=fps, parent=self
        )

        # self.camera_settings should be up-to-date from profile load or wizard
        # Ensure the specific serial being used is part of self.camera_settings for signal connections.
        self.camera_settings["cameraSerialPattern"] = camera_serial

        if self._connect_camera_signals():  # If returns True, there was an issue
            log.error("Failed to connect camera signals. Aborting camera start.")
            self.camera_thread.deleteLater()  # Clean up unstarted/badly configured thread
            self.camera_thread = None
            return

        if initial_settings:
            # SDKCameraThread.run() applies some initial settings like FPS.
            # For other settings from a profile, apply them after a short delay
            # to ensure the device is open in the thread.
            def apply_initial():
                if self.camera_thread:  # Check if thread still exists
                    self.camera_thread.apply_node_settings(initial_settings)
                    log.info(
                        f"Applied initial settings to camera {camera_serial}: {list(initial_settings.keys())}"
                    )

            QTimer.singleShot(200, apply_initial)

        self.camera_thread.start()
        self.statusBar().showMessage(
            f"Camera '{self.camera_settings.get('cameraModel', camera_serial)}' starting...",
            5000,
        )

    def _try_load_last_camera(self):
        """Tries to load the last used camera profile and start the camera."""
        if not prim_app.IC4_INITIALIZED:  # Use global flag from prim_app
            log.info("IC4 not initialized, cannot auto-load last camera.")
            return

        last_profile_name = load_app_setting(SETTING_LAST_PROFILE_NAME)
        if not last_profile_name:
            log.info(
                "No last camera profile saved. User needs to use 'Setup Camera...'."
            )
            self.statusBar().showMessage(
                "No default camera profile. Use Camera > Setup Camera.", 5000
            )
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
            return

        try:
            with open(profile_path, "r") as f:
                profile_settings = json.load(f)
            log.info(f"Successfully loaded last camera profile: {last_profile_name}")

            self.camera_settings = profile_settings

            cam_serial = profile_settings.get("serialPattern")
            if not cam_serial:
                log.error(
                    f"Profile '{last_profile_name}' is missing camera serial pattern."
                )
                return

            initial_cam_settings = {
                **profile_settings.get("defaults", {}),
                **profile_settings.get("advanced", {}),
            }
            target_fps = initial_cam_settings.get("AcquisitionFrameRate", DEFAULT_FPS)

            profile_cti = profile_settings.get("ctiPathUsed")
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
                    "CTI Mismatch",
                    f"Profile '{last_profile_name}' was saved with CTI: {os.path.basename(profile_cti)}\n"
                    f"Current CTI: {os.path.basename(current_cti)}\n\n"
                    "Attempting connection. If issues occur, re-run Camera Setup or Change CTI.",
                )

            self._start_sdk_camera_thread(cam_serial, target_fps, initial_cam_settings)
            # Status bar message moved to _start_sdk_camera_thread for consistency

        except json.JSONDecodeError:
            log.error(f"Failed to parse camera profile: {profile_path}")
            QMessageBox.critical(
                self,
                "Profile Error",
                f"Could not parse profile: {last_profile_name}.json",
            )
        except Exception as e:
            log.exception(
                f"Failed to auto-load/start last camera from '{last_profile_name}': {e}"
            )
            QMessageBox.critical(
                self,
                "Camera Auto-Load Error",
                f"Could not auto-start from '{last_profile_name}':\n{e}",
            )

    def _run_camera_setup(self):
        if not prim_app.IC4_INITIALIZED:  # Use global flag
            QMessageBox.warning(
                self,
                "Camera SDK Not Ready",
                "The camera SDK (IC4) is not initialized. "
                "Please ensure a valid .cti file was selected (the app should have prompted you if needed on startup), "
                "or that the IC Imaging Control SDK is correctly installed.",
            )
            return

        wizard = CameraSetupWizard(self)
        if wizard.exec_() != QDialog.Accepted:
            log.info("Camera Setup Wizard was cancelled.")
            return

        self.camera_settings = wizard.settings
        log.info(
            f"Camera Setup Wizard completed. Settings acquired: {list(self.camera_settings.keys())}"
        )

        profile_name_saved_as = self.camera_settings.get(
            "profileNameSavedAs"
        )  # Base name from wizard
        camera_serial = self.camera_settings.get("cameraSerialPattern")

        if profile_name_saved_as:
            save_app_setting(SETTING_LAST_PROFILE_NAME, profile_name_saved_as)
            log.info(f"Set last profile name to: {profile_name_saved_as}")
        if camera_serial:
            save_app_setting(SETTING_LAST_CAMERA_SERIAL, camera_serial)
            log.info(f"Set last camera serial to: {camera_serial}")

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
            log.error(
                "No camera serial pattern found in wizard settings after completion."
            )
            QMessageBox.critical(
                self, "Setup Error", "Camera setup error: No camera serial identified."
            )

    def _set_initial_splitter_sizes(self):
        if self.bottom_split:
            total_width = self.bottom_split.size().width()
            if total_width > 0:
                left = int(total_width * 0.65)
                right = total_width - left
                self.bottom_split.setSizes([left, right])
            else:
                log.debug(
                    "Cannot set initial splitter sizes yet, total width is 0 (may resolve after window is fully shown)."
                )
        else:
            log.warning("bottom_split not initialized, cannot set initial sizes.")

    def _init_paths_and_icons(self):
        base = os.path.dirname(os.path.abspath(__file__))
        # Correct path to 'icons' assuming it's under 'prim_app/ui/icons'
        # If main_window.py is in prim_app, then 'ui/icons' is relative to base.
        icon_dir = os.path.join(base, "ui", "icons")

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

        self.top_ctrl = TopControlPanel(self)
        top_layout.addWidget(self.top_ctrl)

        if hasattr(self.top_ctrl, "plot_controls"):
            top_layout.addWidget(self.top_ctrl.plot_controls)
        else:
            log.error("self.top_ctrl.plot_controls not found during layout build.")

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
        exp_data = QAction("Export Plot &Data (CSV)…", self)
        exp_data.triggered.connect(self._export_plot_data_as_csv)
        fm.addAction(exp_data)

        exp_img = QAction("Export Plot &Image…", self)
        # Ensure pressure_plot_widget exists before connecting
        if hasattr(self, "pressure_plot_widget") and self.pressure_plot_widget:
            exp_img.triggered.connect(self.pressure_plot_widget.export_as_image)
        else:
            log.error(
                "pressure_plot_widget not initialized for Export Plot Image menu."
            )
        fm.addAction(exp_img)
        fm.addSeparator()
        exit_act = QAction("&Exit", self, shortcut=QKeySequence.Quit)
        exit_act.triggered.connect(self.close)
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
        # Ensure dock_console exists
        if hasattr(self, "dock_console") and self.dock_console:
            vm.addAction(self.dock_console.toggleViewAction())
        else:
            log.error("dock_console not initialized for View menu.")

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
            ):
                self.pressure_plot_widget.reset_zoom(
                    self.top_ctrl.plot_controls.auto_x_cb.isChecked(),
                    self.top_ctrl.plot_controls.auto_y_cb.isChecked(),
                )
            else:
                log.warning("Cannot reset zoom, required components missing.")

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
        """Allows user to select a new CTI file, re-initializing IC4."""
        # Use global IC4_INITIALIZED from prim_app
        if self.camera_thread and self.camera_thread.isRunning():
            QMessageBox.warning(
                self,
                "Camera Active",
                "Please stop the current camera stream before changing the CTI file.",
            )
            return

        current_cti = load_app_setting(SETTING_CTI_PATH, "")
        suggested_dir = (
            os.path.dirname(current_cti)
            if current_cti and os.path.exists(current_cti)
            else ""
        )

        cti_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select New GenTL Producer File (.cti)",
            suggested_dir,
            "CTI Files (*.cti);;All Files (*)",
        )
        if cti_path and os.path.exists(cti_path):
            if (
                os.path.normpath(cti_path) == os.path.normpath(current_cti)
                and prim_app.IC4_INITIALIZED
            ):
                QMessageBox.information(
                    self,
                    "CTI Unchanged",
                    "The selected CTI file is already loaded and initialized.",
                )
                return

            # Attempt to exit existing IC4 library session if initialized
            if prim_app.IC4_INITIALIZED and prim_app.ic4_library_module:
                try:
                    log.info("Exiting IC4 library before changing CTI...")
                    prim_app.ic4_library_module.Library.exit()
                    prim_app.IC4_INITIALIZED = False
                    # prim_app._ic4_init_has_run_successfully_this_session = False # Reset this if you want full re-init capability
                    log.info("IC4 library exited.")
                except Exception as e:
                    log.error(f"Error exiting IC4 library: {e}")
                    QMessageBox.critical(
                        self,
                        "CTI Change Error",
                        f"Could not properly unload previous CTI: {e}. Please restart the application to change CTI.",
                    )
                    return
            else:  # If not initialized, or module not loaded, just proceed
                prim_app.IC4_INITIALIZED = False

            try:
                initialize_ic4_with_cti(
                    cti_path
                )  # This will update prim_app.IC4_INITIALIZED
                if prim_app.IC4_INITIALIZED:
                    save_app_setting(SETTING_CTI_PATH, cti_path)
                    save_app_setting(
                        SETTING_LAST_PROFILE_NAME, None
                    )  # Clear last profile as CTI changed
                    save_app_setting(SETTING_LAST_CAMERA_SERIAL, None)
                    QMessageBox.information(
                        self,
                        "CTI Changed",
                        f"GenTL Producer changed to: {os.path.basename(cti_path)}\n"
                        "Please use 'Camera > Setup Camera...' to configure a camera with this new CTI.",
                    )
                    self.statusBar().showMessage(
                        f"CTI changed: {os.path.basename(cti_path)}", 5000
                    )
                else:
                    QMessageBox.critical(
                        self,
                        "CTI Load Error",
                        f"Failed to initialize with new CTI: {os.path.basename(cti_path)}."
                        "\nThe previous CTI (if any) is no longer active.",
                    )
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "CTI Exception",
                    f"Error loading new CTI {os.path.basename(cti_path)}: {e}",
                )
                log.exception(f"Exception changing CTI to '{cti_path}'.")
        elif cti_path:  # Path given but doesn't exist
            QMessageBox.warning(
                self,
                "File Not Found",
                f"The selected CTI file was not found: {cti_path}",
            )

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
                QMessageBox.information(
                    self,
                    "Recording Stopped",
                    "PRIM device disconnected during recording.",
                )
                self._trigger_stop_recording()
        self._update_recording_actions_enable_state()

    @pyqtSlot(int, float, float)
    def _handle_new_serial_data(self, idx: int, t: float, p: float):
        if self.top_ctrl and hasattr(self.top_ctrl, "plot_controls"):
            self.top_ctrl.update_prim_data(idx, t, p)
            ax = self.top_ctrl.plot_controls.auto_x_cb.isChecked()
            ay = self.top_ctrl.plot_controls.auto_y_cb.isChecked()
            if self.pressure_plot_widget:
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

    @pyqtSlot(str)
    def _handle_serial_error(self, msg: str):
        log.error(f"Serial error: {msg}")
        self.statusBar().showMessage(f"Serial Error: {msg}", 6000)
        self._update_recording_actions_enable_state()

    @pyqtSlot()
    def _handle_serial_thread_finished(self):
        log.info("SerialThread finished signal received.")
        sender_thread = self.sender()
        if self._serial_thread is sender_thread:
            current_status_text = (
                self.top_ctrl.conn_lbl.text().lower()
                if self.top_ctrl and hasattr(self.top_ctrl, "conn_lbl")
                else ""
            )
            is_ui_connected = (
                "connected" in current_status_text
                or "opened serial port" in current_status_text
            )
            if is_ui_connected:
                self._handle_serial_status_change("Disconnected by thread finishing")

            # Ensure deleteLater is called on the correct object if it exists
            if self._serial_thread:
                self._serial_thread.deleteLater()
            self._serial_thread = None  # Crucial to set to None
            log.info("SerialThread instance cleaned up.")
        else:
            log.warning(
                "Received 'finished' signal from an old or unknown SerialThread instance. Current thread might be different or None."
            )
            if sender_thread:  # If we can, schedule the sender for deletion anyway
                sender_thread.deleteLater()

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
                if (
                    self._serial_thread
                ):  # Cleanup old thread if it somehow exists but isn't running
                    if (
                        self._serial_thread.isRunning()
                    ):  # Should have been caught by first if
                        log.warning(
                            "Unexpected: serial thread exists and is running. Stopping."
                        )
                        self._serial_thread.stop()
                        if not self._serial_thread.wait(1000):
                            self._serial_thread.terminate()
                    self._serial_thread.deleteLater()
                    self._serial_thread = None

                self._serial_thread = SerialThread(port=port, parent=self)
                self._serial_thread.data_ready.connect(self._handle_new_serial_data)
                self._serial_thread.error_occurred.connect(self._handle_serial_error)
                self._serial_thread.status_changed.connect(
                    self._handle_serial_status_change
                )
                # Connect finished *after* other signals to ensure status updates occur first
                self._serial_thread.finished.connect(
                    self._handle_serial_thread_finished
                )
                self._serial_thread.start()
            except Exception as e:
                log.exception("Failed to start SerialThread.")
                QMessageBox.critical(self, "Serial Error", str(e))
                if self._serial_thread:
                    self._serial_thread.deleteLater()
                self._serial_thread = None
                self._update_recording_actions_enable_state()

    def _update_recording_actions_enable_state(self):
        serial_ready = (
            self._serial_thread is not None and self._serial_thread.isRunning()
        )
        can_start_recording = serial_ready and not self._is_recording
        if hasattr(self, "start_recording_action"):
            self.start_recording_action.setEnabled(bool(can_start_recording))
        if hasattr(self, "stop_recording_action"):
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

        recording_base_prefix = os.path.join(session_folder, session_name_safe)
        self.last_trial_basepath = session_folder

        w, h = DEFAULT_FRAME_SIZE
        if self.camera_thread and self.camera_settings:
            res_str_from_defaults = self.camera_settings.get("defaults", {}).get(
                "Resolution"
            )
            res_str_from_panel = (
                self.camera_panel.res_combo.currentText() if self.camera_panel else None
            )

            res_str = res_str_from_defaults  # Prioritize what's in loaded/wizard settings defaults
            if (
                not res_str and res_str_from_panel
            ):  # Fallback to live panel if not in defaults
                res_str = res_str_from_panel
                log.info("Using live resolution from panel for recording frame size.")
            elif res_str_from_defaults:
                log.info(
                    "Using resolution from camera_settings.defaults for recording frame size."
                )

            if res_str and "x" in res_str:
                try:
                    w_str, h_str = res_str.split("x")
                    w, h = int(w_str), int(h_str)
                except ValueError:
                    log.warning(
                        f"Could not parse resolution '{res_str}'. Defaulting to {DEFAULT_FRAME_SIZE}."
                    )
                    w, h = DEFAULT_FRAME_SIZE
            else:
                log.info(
                    f"Resolution for recording not found or invalid. Defaulting to {DEFAULT_FRAME_SIZE}."
                )
        else:
            log.info(
                f"Camera not active or settings not available. Defaulting recording frame size to {DEFAULT_FRAME_SIZE}."
            )

        video_ext = DEFAULT_VIDEO_EXTENSION.lower()
        codec = DEFAULT_VIDEO_CODEC

        # Get FPS for recording
        # Prioritize from camera settings, then panel, then default
        record_fps = DEFAULT_FPS
        if (
            self.camera_settings
            and "defaults" in self.camera_settings
            and "AcquisitionFrameRate" in self.camera_settings["defaults"]
        ):
            record_fps = self.camera_settings["defaults"]["AcquisitionFrameRate"]
            log.info(
                f"Using FPS from camera_settings.defaults for recording: {record_fps}"
            )
        elif self.camera_panel and self.camera_panel.fps_spin.value() > 0:
            record_fps = self.camera_panel.fps_spin.value()
            log.info(f"Using FPS from camera_panel for recording: {record_fps}")
        else:
            log.info(f"Using default FPS for recording: {record_fps}")

        log.info(
            f"Attempting to start recording session: '{session_name_safe}' in folder '{session_folder}'"
        )
        log.info(
            f"Parameters for RecordingWorker: FPS: {record_fps}, FrameSize: {w}x{h}, VideoFormat: {video_ext}, Codec: {codec}"
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
            self._recording_worker = RecordingWorker(
                basepath=recording_base_prefix,
                fps=record_fps,
                frame_size=(w, h),
                video_ext=video_ext,
                video_codec=codec,
                parent=self,
            )
            self._recording_worker.start()
            QThread.msleep(250)

            if not (
                self._recording_worker
                and self._recording_worker.isRunning()
                and self._recording_worker.is_ready_to_record
            ):
                log.error(
                    "Recording worker did not become ready. Check logs for TrialRecorder init errors."
                )
                if self._recording_worker:
                    if self._recording_worker.isRunning():
                        self._recording_worker.stop_worker()
                    self._recording_worker.deleteLater()  # Ensure it's cleaned up
                    self._recording_worker = None
                raise RuntimeError(
                    "Recording worker failed to initialize TrialRecorder or start."
                )
        except Exception as e:
            log.exception(f"Failed to initialize or start RecordingWorker: {e}")
            QMessageBox.critical(
                self, "Recording Error", f"Could not start recording worker: {e}"
            )
            if self._recording_worker:
                if self._recording_worker.isRunning():
                    self._recording_worker.stop_worker()
                self._recording_worker.deleteLater()  # Ensure it's cleaned up
                self._recording_worker = None
            return

        self._is_recording = True
        if hasattr(self, "start_recording_action"):
            self.start_recording_action.setIcon(self.icon_recording_active)
        self._update_recording_actions_enable_state()
        if self.pressure_plot_widget:
            self.pressure_plot_widget.clear_plot()
        self.statusBar().showMessage(f"Recording Started: {session_name_safe}", 0)

    def _trigger_stop_recording(self):
        if not self._is_recording or not self._recording_worker:
            log.info("Stop recording triggered, but not recording or worker missing.")
            if self._is_recording:
                self._is_recording = False  # Correct state if worker is missing
            self._update_recording_actions_enable_state()
            return

        log.info("Stopping recording worker...")
        try:
            self._recording_worker.stop_worker()
            if not self._recording_worker.wait(
                7000
            ):  # Increased timeout for potentially large files
                log.warning(
                    "Recording worker did not stop gracefully after 7s. Terminating."
                )
                self._recording_worker.terminate()
                self._recording_worker.wait(1000)  # Brief wait after terminate

            count = self._recording_worker.video_frame_count
            self.statusBar().showMessage(
                f"Recording Stopped. {count} frames saved.", 7000
            )

            # Save plot data for the just-stopped recording *before* asking to open folder
            if hasattr(self, "last_trial_basepath") and self.last_trial_basepath:
                self._save_current_plot_data_for_session()
            else:
                log.warning(
                    "last_trial_basepath not set, cannot save session plot data automatically."
                )

            reply = QMessageBox.information(
                self,
                "Recording Saved",
                f"Session saved to:\n{self.last_trial_basepath}\n\nOpen folder?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if (
                reply == QMessageBox.Yes
                and hasattr(self, "last_trial_basepath")
                and self.last_trial_basepath
            ):
                if sys.platform == "win32":
                    os.startfile(self.last_trial_basepath)
                elif sys.platform == "darwin":
                    os.system(f'open "{self.last_trial_basepath}"')
                else:
                    os.system(f'xdg-open "{self.last_trial_basepath}"')
        except Exception as e:
            log.exception(f"Error during the stop recording process: {e}")
            self.statusBar().showMessage("Error stopping recording.", 5000)
        finally:
            if self._recording_worker:
                if (
                    self._recording_worker.isRunning()
                ):  # Should not be running if wait succeeded
                    log.warning(
                        "Recording worker still running in finally. Forcing stop."
                    )
                    # stop_worker might have already put a sentinel, but try again if terminating
                    if (
                        not self._recording_worker.isFinished()
                    ):  # Only terminate if not already finished
                        self._recording_worker.terminate()
                        self._recording_worker.wait(500)
                self._recording_worker.deleteLater()
            self._recording_worker = None  # Crucial
            self._is_recording = False
            if hasattr(self, "start_recording_action"):
                self.start_recording_action.setIcon(self.icon_record_start)
            self._update_recording_actions_enable_state()
            log.info("Recording fully stopped and UI updated.")

    def _save_current_plot_data_for_session(self):
        """Saves the current pressure plot data to a CSV file within the last trial basepath."""
        if not hasattr(self, "last_trial_basepath") or not self.last_trial_basepath:
            log.warning(
                "last_trial_basepath not set. Cannot save plot data for session."
            )
            return
        if not (self.pressure_plot_widget and self.pressure_plot_widget.times):
            log.info("No plot data to save for the session.")
            return

        session_name_from_folder = os.path.basename(self.last_trial_basepath)
        csv_filename = f"{session_name_from_folder}_pressure_data.csv"
        csv_path = os.path.join(self.last_trial_basepath, csv_filename)

        try:
            with open(csv_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["time_s", "pressure_mmHg"])  # Header
                for t, p in zip(
                    self.pressure_plot_widget.times, self.pressure_plot_widget.pressures
                ):
                    writer.writerow([f"{t:.6f}", f"{p:.6f}"])
            log.info(f"Session plot data saved to {csv_path}")
            self.statusBar().showMessage(
                f"Plot CSV for session saved to {os.path.basename(csv_path)}", 5000
            )
        except Exception as e:
            log.exception(f"Failed to save session plot CSV to {csv_path}: {e}")
            QMessageBox.warning(
                self, "Plot CSV Export Error", f"Could not save session plot CSV: {e}"
            )

    @pyqtSlot()
    def _clear_pressure_plot(self):
        if self.pressure_plot_widget:
            self.pressure_plot_widget.clear_plot()
            self.statusBar().showMessage("Pressure plot cleared.", 3000)
        else:
            log.warning("Pressure plot widget not available to clear.")

    @pyqtSlot()
    def _export_plot_data_as_csv(self):
        if not (self.pressure_plot_widget and self.pressure_plot_widget.times):
            QMessageBox.information(self, "No Plot Data", "Nothing to export.")
            return
        default_name = f"plot_data_export_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Plot Data",
            default_name,
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
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
        full_msg = f"Camera Error: {msg}"
        if code:
            full_msg += f"\n(SDK Code: {code})"
        log.error(full_msg)
        QMessageBox.critical(self, "Camera Error", full_msg)

        if self.camera_thread and self.camera_thread.isRunning():
            try:
                self.camera_thread.stop()
                self.camera_thread.wait(1000)  # Give it a moment
            except Exception as e:
                log.error(f"Error trying to stop camera thread after error: {e}")
        # Potentially disable camera controls or update UI to show camera error state
        if self.camera_panel:
            self.camera_panel.setEnabled(False)  # Example: disable panel
        self.statusBar().showMessage("Camera Error Occurred. Stream stopped.", 0)

    def closeEvent(self, event):
        log.info("Close event triggered for MainWindow.")
        if self._is_recording:
            reply = QMessageBox.question(
                self,
                "Confirm Exit",
                "Recording is in progress. Stop and exit?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                log.info("User chose to stop recording and exit.")
                self._trigger_stop_recording()  # This should handle worker cleanup
                QApplication.processEvents()
            else:
                log.info("User cancelled exit during recording.")
                event.ignore()
                return

        # Ensure threads are stopped even if not recording
        if self._recording_worker and self._recording_worker.isRunning():
            log.info(
                "Stopping recording worker on close (was not stopped by _trigger_stop_recording)..."
            )
            self._recording_worker.stop_worker()
            if not self._recording_worker.wait(3000):
                log.warning(
                    "Recording worker did not stop gracefully on close. Terminating."
                )
                self._recording_worker.terminate()
        if self._recording_worker:
            self._recording_worker.deleteLater()  # Schedule for deletion
        self._recording_worker = None

        if self._serial_thread and self._serial_thread.isRunning():
            log.info("Stopping serial thread on close...")
            self._serial_thread.stop()
            if not self._serial_thread.wait(2000):
                log.warning(
                    "Serial thread did not stop gracefully on close. Terminating."
                )
                self._serial_thread.terminate()
        if self._serial_thread:
            self._serial_thread.deleteLater()
        self._serial_thread = None

        if self.camera_thread and self.camera_thread.isRunning():
            log.info("Stopping camera thread on close...")
            self.camera_thread.stop()
            if not self.camera_thread.wait(2000):
                log.warning(
                    "Camera thread did not stop gracefully on close. Terminating."
                )
                self.camera_thread.terminate()
        if self.camera_thread:
            self.camera_thread.deleteLater()
        self.camera_thread = None

        log.info("Proceeding with application close.")
        super().closeEvent(event)
