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
    QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSlot, QTimer, QVariant, QDateTime, QSize
from PyQt5.QtGui import QIcon, QKeySequence

import prim_app
from prim_app import initialize_ic4_with_cti, is_ic4_fully_initialized
import imagingcontrol4 as ic4

from utils.app_settings import (
    save_app_setting,
    load_app_setting,
    SETTING_CTI_PATH,
    SETTING_LAST_CAMERA_SERIAL,
    save_app_setting,  # Ensure this was the fix for the import error
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
    # CAMERA_HARDCODED_DEFAULTS, # Temporarily remove usage
)

from ui.control_panels.top_control_panel import TopControlPanel
from ui.control_panels.camera_control_panel import CameraControlPanel
from ui.canvas.gl_viewfinder import GLViewfinder
from ui.canvas.pressure_plot_widget import PressurePlotWidget
from threads.sdk_camera_thread import SDKCameraThread
from camera.setup_wizard import CameraSetupWizard  # Will be simplified
from threads.serial_thread import SerialThread
from recording import RecordingWorker
from utils.utils import list_serial_ports

log = logging.getLogger(__name__)


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
        self.camera_panel = None
        self.camera_view = None
        self.bottom_split = None
        self.camera_settings = {}  # Still useful for storing basic info like serial

        self._init_paths_and_icons()
        self._build_console_log_dock()
        self._build_central_widget_layout()  # camera_panel is created here
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

        self.setWindowTitle(f"{APP_NAME} - v{APP_VERSION}")

        self._check_and_prompt_for_cti_on_startup()
        if is_ic4_fully_initialized():
            QTimer.singleShot(0, self._initialize_camera_on_startup)
        else:
            self.statusBar().showMessage(
                "IC4 SDK not fully configured. Use Camera > Setup...", 5000
            )
            if self.camera_panel:
                self.camera_panel.setEnabled(False)

        # self.showMaximized() # Already called later
        QTimer.singleShot(50, self._set_initial_splitter_sizes)
        self._set_initial_control_states()
        log.info("MainWindow initialized.")
        self.showMaximized()

    def _set_initial_splitter_sizes(self):
        if (
            self.bottom_split and self.bottom_split.count() == 2
        ):  # Ensure splitter has children
            # Defer sizing slightly to allow the main window to fully show and report correct dimensions
            QTimer.singleShot(100, self._perform_splitter_sizing)

    def _perform_splitter_sizing(self):
        """Actually sets the splitter sizes. Called by a QTimer."""
        if self.bottom_split and self.bottom_split.count() == 2:
            w = self.bottom_split.width()
            h = self.bottom_split.height()
            if w > 0 and h > 0:
                # Example: Give ~65% width to viewfinder, ~35% to plot, or adjust as you like
                self.bottom_split.setSizes([int(w * 0.65), int(w * 0.35)])
                log.debug(f"Splitter sizes set for width {w}")
            else:
                # If still not sized, could retry once more or log a warning
                log.warning("Bottom splitter not ready for sizing after delay.")
                # QTimer.singleShot(200, self._perform_splitter_sizing) # Optional: one more retry

    def _check_and_prompt_for_cti_on_startup(self):
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
                    # The save_app_setting was confirmed to be the fix for the import error
                    save_app_setting(SETTING_CTI_PATH, cti)
                    QMessageBox.information(
                        self, "CTI Loaded", f"Loaded: {os.path.basename(cti)}"
                    )
                    self.statusBar().showMessage(f"CTI: {os.path.basename(cti)}", 5000)
                except Exception as e:
                    QMessageBox.critical(self, "CTI Error", str(e))
            else:
                self.statusBar().showMessage(
                    "No CTI file selected. Camera functionality may be limited.", 5000
                )
                if self.camera_panel:
                    self.camera_panel.setEnabled(False)
        elif is_ic4_fully_initialized():
            self.statusBar().showMessage(
                f"IC4 initialized with CTI: {os.path.basename(load_app_setting(SETTING_CTI_PATH, ''))}",
                5000,
            )

    def _connect_camera_signals(self):
        th = self.camera_thread
        cp = self.camera_panel  # This is your tabbed CameraControlPanel

        if not (th and self.camera_view and cp):
            log.warning(
                "Cannot connect camera signals: thread, view, or camera_panel missing."
            )
            return True

        # --- Disconnect ALL signals from th and cp first to prevent multiple connections ---
        # (More robustly, check if connected before disconnecting, or use QObject.disconnect())
        try:
            th.frame_ready.disconnect(self.camera_view.update_frame)
        except TypeError:
            pass
        try:
            th.camera_error.disconnect(self._on_camera_error)
        except TypeError:
            pass

        if hasattr(th, "camera_info_updated"):
            try:
                th.camera_info_updated.disconnect(self._update_camera_status_tab)
            except TypeError:
                pass
        if hasattr(th, "exposure_params_updated"):
            try:
                th.exposure_params_updated.disconnect(
                    self._update_camera_exposure_controls
                )
            except TypeError:
                pass
        # Add for gain later:
        # if hasattr(th, 'gain_params_updated'):
        # try: th.gain_params_updated.disconnect(self._update_camera_gain_controls)
        # except TypeError: pass

        # --- Connect SDKCameraThread signals to MainWindow/CameraPanel slots ---
        th.frame_ready.connect(self.camera_view.update_frame)
        th.camera_error.connect(self._on_camera_error)

        if hasattr(th, "camera_info_updated"):
            th.camera_info_updated.connect(self._update_camera_status_tab)
        if hasattr(th, "exposure_params_updated"):
            th.exposure_params_updated.connect(self._update_camera_exposure_controls)
        # Add for gain later:
        # if hasattr(th, 'gain_params_updated'):
        # th.gain_params_updated.connect(self._update_camera_gain_controls)

        # --- Connect CameraControlPanel UI signals to MainWindow slots (for sending commands to thread) ---
        # For Exposure
        if hasattr(cp, "auto_exp_cb"):
            try:
                cp.auto_exp_cb.toggled.disconnect(
                    self._on_auto_exposure_changed
                )  # Use toggled for QCheckBox
            except TypeError:
                pass
            cp.auto_exp_cb.toggled.connect(self._on_auto_exposure_changed)

        if hasattr(cp, "exp_spin"):
            try:
                cp.exp_spin.valueChanged.disconnect(self._on_exposure_time_changed)
            except TypeError:
                pass
            cp.exp_spin.valueChanged.connect(self._on_exposure_time_changed)

        # Add for Gain later
        # if hasattr(cp, 'gain_spin'):
        # try: cp.gain_spin.valueChanged.disconnect(self._on_gain_changed)
        # except TypeError: pass
        # cp.gain_spin.valueChanged.connect(self._on_gain_changed)

        # Add for Resolution, PixelFormat, FPS later if re-enabled

        log.info("Camera signals connected for live feed and initial controls.")
        return False

    @pyqtSlot(bool)
    def _on_auto_exposure_changed(self, checked: bool):
        if self.camera_thread and self.camera_thread.isRunning():
            exposure_auto_str = "Continuous" if checked else "Off"
            log.debug(f"UI changed: ExposureAuto to {exposure_auto_str}")
            self.camera_thread._attempt_set_property(
                "ExposureAuto", exposure_auto_str, exposure_auto_str
            )
            # Re-query exposure params to update UI state (e.g., enable/disable manual exposure spinbox)
            # This is a bit indirect; ideally, SDKCameraThread confirms the change and re-emits params.
            # For now, let's assume the set was successful and update UI based on 'checked'.
            if self.camera_panel and hasattr(self.camera_panel, "exp_spin"):
                self.camera_panel.exp_spin.setEnabled(not checked)

    @pyqtSlot(float)
    def _on_exposure_time_changed(self, value_us: float):
        if self.camera_thread and self.camera_thread.isRunning():
            # Only set if auto exposure is off
            if (
                self.camera_panel
                and hasattr(self.camera_panel, "auto_exp_cb")
                and not self.camera_panel.auto_exp_cb.isChecked()
            ):
                log.debug(f"UI changed: ExposureTime to {value_us} µs")
                self.camera_thread._attempt_set_property(
                    "ExposureTime", value_us, f"{value_us}"
                )

    # Add _on_gain_changed etc. later

    # --- New SLOTS in MainWindow to update CameraControlPanel from SDKCameraThread signals ---
    @pyqtSlot(dict)
    def _update_camera_status_tab(self, info: dict):
        if self.camera_panel and hasattr(self.camera_panel, "update_status_info"):
            self.camera_panel.update_status_info(
                model=info.get("model", "N/A"),
                serial=info.get("serial", "N/A"),
                resolution=f"{info.get('width','N/A')}x{info.get('height','N/A')}",
                pix_format=info.get("pixel_format", "N/A"),
                fps=f"{info.get('fps', 0.0):.1f}",
            )
            log.debug(f"Camera status tab updated: {info}")

    @pyqtSlot(dict)
    def _update_camera_exposure_controls(self, params: dict):
        if self.camera_panel and hasattr(self.camera_panel, "update_exposure_controls"):
            self.camera_panel.update_exposure_controls(
                enabled=params.get("is_writable", False)
                or params.get(
                    "auto_is_writable", False
                ),  # Enable if either is writable
                is_auto=params.get("auto_on", False),
                value_us=params.get("current_us", 0.0),
                min_us=params.get("min_us", 0.0),
                max_us=params.get("max_us", 1000000.0),
            )
            log.debug(f"Camera exposure controls updated: {params}")
            # Ensure adjustments tab is enabled if controls are active
            if (
                hasattr(self.camera_panel, "tab_widget")
                and self.camera_panel.tab_widget.count() > 1
            ):
                self.camera_panel.tab_widget.setTabEnabled(
                    1, True
                )  # Index 1 for "Adjustments" tab

    # Ensure it doesn't unconditionally disable camera_panel if it was enabled by _initialize_camera_on_startup.
    def _start_sdk_camera_thread(self, camera_identifier, fps, initial_settings=None):
        if self.camera_thread and self.camera_thread.isRunning():
            log.info("Stopping existing camera thread...")
            self.camera_thread.stop()
            self.camera_thread.deleteLater()
            self.camera_thread = None
            QApplication.processEvents()

        log.info(f"Creating SDKCameraThread for device: '{camera_identifier}'")
        self.camera_thread = SDKCameraThread(
            device_name=camera_identifier, fps=float(fps), parent=self
        )
        self.camera_settings["cameraSerialPattern"] = camera_identifier

        if (
            self._connect_camera_signals()
        ):  # This connects frame_ready, error, and new status/param signals
            log.error("Failed to connect camera signals for SDKCameraThread.")
            if self.camera_panel:
                self.camera_panel.setEnabled(False)
            return

        log.info(f"Starting SDKCameraThread for {camera_identifier}...")
        self.camera_thread.start()
        # camera_panel should already be enabled by _initialize_camera_on_startup if IC4 is ready
        self.statusBar().showMessage(
            f"Attempting basic live feed: {self.camera_settings.get('cameraModel', camera_identifier)}",
            5000,
        )

    def _initialize_camera_on_startup(self):  # Modified to update status tab
        if not is_ic4_fully_initialized():
            log.info("IC4 not fully initialized.")
            self.statusBar().showMessage(
                "IC4 SDK not configured. Use Camera menu...", 5000
            )
            if self.camera_panel:
                self.camera_panel.setEnabled(False)
            return

        log.info("Attempting to get first available IC4 camera...")
        if self.camera_panel:
            self.camera_panel.setEnabled(
                True
            )  # Enable the panel as we are trying to use camera
            if (
                hasattr(self.camera_panel, "tab_widget")
                and self.camera_panel.tab_widget.count() > 1
            ):
                # self.camera_panel.tab_widget.setTabEnabled(1, False) # Keep adjustments initially disabled until params arrive
                pass  # Let controls be enabled by default, their interactive state depends on camera signals

        available_devices = []
        try:
            available_devices = ic4.DeviceEnum.devices()
            if not available_devices:
                log.warning("No IC4 devices found.")
                self.statusBar().showMessage("No cameras found.", 5000)
                if self.camera_panel:
                    self.camera_panel.setEnabled(False)
                return
        except Exception as e:
            log.error(f"Error enumerating IC4 devices: {e}")
            self.statusBar().showMessage(f"Error enumerating devices: {e}", 5000)
            if self.camera_panel:
                self.camera_panel.setEnabled(False)
            return

        first_device_info = available_devices[0]
        camera_model_name = (
            first_device_info.model_name
            if hasattr(first_device_info, "model_name")
            else "Unknown Model"
        )
        camera_serial_number = (
            first_device_info.serial
            if hasattr(first_device_info, "serial") and first_device_info.serial
            else "N/A"
        )
        camera_identifier = (
            camera_serial_number
            if camera_serial_number != "N/A"
            else (
                first_device_info.unique_name
                if hasattr(first_device_info, "unique_name")
                and first_device_info.unique_name
                else camera_model_name
            )
        )

        if not camera_identifier:  # Should not happen if model_name is fallback
            log.error(f"Could not ID first camera: {camera_model_name}")
            self.statusBar().showMessage(f"Could not ID {camera_model_name}.", 5000)
            if self.camera_panel:
                self.camera_panel.setEnabled(False)
            return

        log.info(f"Found first camera: {camera_model_name} (ID: {camera_identifier}).")
        self.camera_settings["cameraModel"] = camera_model_name
        self.camera_settings["cameraSerial"] = camera_serial_number
        self.camera_settings["cameraIdentifier"] = camera_identifier

        try:
            self._start_sdk_camera_thread(
                camera_identifier, DEFAULT_FPS, initial_settings=None
            )
            save_app_setting(SETTING_LAST_CAMERA_SERIAL, camera_identifier)

            # Initial update for status tab - SDKThread will send more complete info via signal
            if self.camera_panel and hasattr(self.camera_panel, "update_status_info"):
                self.camera_panel.update_status_info(
                    model=self.camera_settings.get("cameraModel", "N/A"),
                    serial=self.camera_settings.get("cameraSerial", "N/A"),
                    resolution="640x480 (Target)",  # This is what SDKCameraThread sets
                    pix_format="Mono8 (Target)",  # This is what SDKCameraThread sets
                    fps=f"~{DEFAULT_FPS} (Target)",  # Actual FPS will come from SDKCameraThread signal
                )
        except Exception as e:
            log.exception(f"Failed to start camera '{camera_model_name}': {e}")
            QMessageBox.critical(
                self, "Camera Start Error", f"Could not start {camera_model_name}:\n{e}"
            )
            if self.camera_panel:
                self.camera_panel.setEnabled(False)

    def _set_initial_control_states(self):  # Your existing method is mostly fine
        if self.top_ctrl:
            self.top_ctrl.update_connection_status("Disconnected", False)
        if hasattr(self, "start_recording_action"):
            self.start_recording_action.setEnabled(False)
        if hasattr(self, "stop_recording_action"):
            self.stop_recording_action.setEnabled(False)

        if self.camera_panel:
            self.camera_panel.setEnabled(False)  # Start disabled
            # Ensure the "Adjustments" tab controls are initially disabled if the panel itself is disabled.
            # Or, individual controls within CameraControlPanel can set their own initial enabled state.
            # For now, disabling the whole panel is sufficient at start.
            # The "Adjustments" tab itself can be enabled, but its widgets will be disabled
            # until specific camera parameters are received.
            if (
                hasattr(self.camera_panel, "tab_widget")
                and self.camera_panel.tab_widget.count() > 1
            ):
                self.camera_panel.tab_widget.setTabEnabled(
                    1, True
                )  # Keep tab enabled, but panel's setEnabled(False) will disable contents.

    def _run_camera_setup(self):
        # Temporarily disable the camera setup wizard functionality
        log.info("Camera Setup Wizard is temporarily disabled for simplified testing.")
        QMessageBox.information(
            self,
            "Camera Setup",
            "Camera setup is temporarily simplified. The application will attempt to use the first detected camera.",
        )
        # Optionally, you could trigger a re-scan/re-init of the simplified camera startup
        # if is_ic4_fully_initialized():
        #     self._initialize_camera_on_startup()
        pass

    def _init_paths_and_icons(self):
        base = os.path.dirname(os.path.abspath(__file__))
        icon_dir = os.path.join(base, "ui", "icons")
        if not os.path.isdir(icon_dir):
            # Attempt to find icons if script is run from within prim_app directory
            alt_icon_dir = os.path.join(
                os.path.dirname(base), "prim_app", "ui", "icons"
            )
            if os.path.isdir(alt_icon_dir):
                icon_dir = alt_icon_dir
            else:  # Try one level up from base for cases like running tests from project root
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
        central = QWidget()
        self.setCentralWidget(central)  # Set central widget first

        main_v_layout = QVBoxLayout(
            central
        )  # Main vertical layout for the central widget
        main_v_layout.setContentsMargins(2, 2, 2, 2)  # Minimal margins
        main_v_layout.setSpacing(3)  # Minimal spacing

        # --- Top Row for Control Panels ---
        self.top_row_widget = QWidget()  # Explicit container for the top row
        top_h_layout = QHBoxLayout(self.top_row_widget)
        top_h_layout.setContentsMargins(0, 0, 0, 0)  # No margins for the layout itself
        top_h_layout.setSpacing(4)  # Minimal spacing between panels

        # Instantiate your (now tabbed) CameraControlPanel
        self.camera_panel = CameraControlPanel(self)
        # Initial enabled state will be handled by _set_initial_control_states

        # Instantiate TopControlPanel (which internally contains PlotControlPanel)
        self.top_ctrl = TopControlPanel(self)

        # Add panels to the top horizontal layout
        top_h_layout.addWidget(
            self.camera_panel, 1
        )  # Adjust stretch factor as needed (e.g., 1)
        top_h_layout.addWidget(
            self.top_ctrl, 2
        )  # Adjust stretch factor (e.g., 2, giving it more width)

        # Crucial for making the top row compact vertically:
        self.top_row_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

        main_v_layout.addWidget(
            self.top_row_widget, 0
        )  # Stretch factor 0 for top row (take minimum height)

        # --- Bottom Splitter for Viewfinder and Plot ---
        self.bottom_split = QSplitter(Qt.Horizontal)
        self.bottom_split.setChildrenCollapsible(False)  # Good practice

        self.camera_view = GLViewfinder(self)
        self.pressure_plot_widget = PressurePlotWidget(self)

        self.bottom_split.addWidget(self.camera_view)
        self.bottom_split.addWidget(self.pressure_plot_widget)

        # Initial stretch factors for the splitter widgets (e.g., give more space to viewfinder)
        self.bottom_split.setStretchFactor(0, 2)
        self.bottom_split.setStretchFactor(1, 1)

        main_v_layout.addWidget(
            self.bottom_split, 1
        )  # Stretch factor 1 for bottom area (take available space)

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
        about_act = QAction(
            f"&About {APP_NAME}", self, triggered=self._show_about_dialog
        )
        hm.addAction(about_act)
        hm.addAction("About &Qt", QApplication.instance().aboutQt)

        cam_menu = mb.addMenu("&Camera")
        setup_cam_act = QAction(
            "Setup Camera… (Simplified)", self, triggered=self._run_camera_setup
        )
        cam_menu.addAction(setup_cam_act)
        change_cti_act = QAction(
            "Change CTI File...", self, triggered=self._change_cti_file
        )
        cam_menu.addAction(change_cti_act)

    def _change_cti_file(self):
        # Prompt user for CTI file
        current_cti_path = load_app_setting(SETTING_CTI_PATH, "")
        cti_dir = os.path.dirname(current_cti_path) if current_cti_path else ""

        cti_path, _ = QFileDialog.getOpenFileName(
            self, "Select GenTL Producer File (.cti)", cti_dir, "*.cti"
        )
        if not cti_path or not os.path.exists(cti_path):
            log.info("No CTI file selected or file does not exist.")
            return

        # Stop existing camera thread if running
        if self.camera_thread and self.camera_thread.isRunning():
            log.info("Stopping existing camera thread before changing CTI file.")
            self.camera_thread.stop()
            self.camera_thread.deleteLater()
            self.camera_thread = None
            if self.camera_panel:
                self.camera_panel.setEnabled(False)  # Ensure panel is disabled
            QApplication.processEvents()  # Allow thread to clean up
            log.info("Existing camera thread stopped for CTI change.")

        try:
            # Re-initialize IC4 with the new CTI path.
            # The prim_app.initialize_ic4_with_cti function should handle os.environ and ic4.Library.init()
            # It might also need to handle ic4.Library.exit() if it was already initialized.
            # For simplicity here, assuming initialize_ic4_with_cti manages this.
            # If not, we might need to explicitly call ic4.Library.exit() before re-initializing.
            if prim_app.IC4_LIBRARY_INITIALIZED:  # Check if library was init before
                log.info("Exiting IC4 library before re-initializing with new CTI...")
                ic4.Library.exit()
                prim_app.IC4_LIBRARY_INITIALIZED = False  # Reset flag
                prim_app.IC4_GENTL_SYSTEM_CONFIGURED = False

            initialize_ic4_with_cti(
                cti_path
            )  # This will set GENICAM_GENTL64_PATH and ic4.Library.init()
            save_app_setting(SETTING_CTI_PATH, cti_path)  # Persist the new CTI path

            QMessageBox.information(
                self,
                "CTI Changed",
                f"Successfully loaded new CTI file:\n{os.path.basename(cti_path)}\n\nPlease restart the application for changes to fully take effect if issues persist, or attempt to re-initialize camera via menu.",
            )
            self.statusBar().showMessage(
                f"CTI changed to: {os.path.basename(cti_path)}. Restart or re-init camera.",
                7000,
            )

            # Attempt to re-initialize the camera with the new CTI settings
            if is_ic4_fully_initialized():
                QTimer.singleShot(
                    0, self._initialize_camera_on_startup
                )  # Try to get the camera running again
            else:
                if self.camera_panel:
                    self.camera_panel.setEnabled(False)

        except Exception as exc:
            log.exception(
                f"Failed to change and initialize with new CTI file '{cti_path}': {exc}"
            )
            QMessageBox.critical(
                self,
                "CTI Change Error",
                f"Could not load or initialize with new CTI file:\n{exc}",
            )
            if self.camera_panel:
                self.camera_panel.setEnabled(
                    False
                )  # Ensure panel remains disabled on error

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
        self.serial_port_combobox.addItem(
            "🔌 Simulated Data", QVariant()
        )  # Ensure QVariant for None/empty
        ports = list_serial_ports()
        if ports:
            for p_dev, p_desc in ports:
                self.serial_port_combobox.addItem(
                    f"{os.path.basename(p_dev)} ({p_desc})", QVariant(p_dev)
                )
        else:
            self.serial_port_combobox.addItem(
                "No Serial Ports Found", QVariant()
            )  # QVariant for None
            self.serial_port_combobox.setEnabled(False)
        tb.addWidget(self.serial_port_combobox)
        tb.addSeparator()
        if hasattr(self, "start_recording_action"):
            tb.addAction(self.start_recording_action)
        if hasattr(self, "stop_recording_action"):
            tb.addAction(self.stop_recording_action)

    def _build_status_bar(self):
        sb = self.statusBar()
        # self.setStatusBar(sb) # Not needed, statusBar() returns the existing one or creates it
        self.app_session_time_label = QLabel("Session: 00:00:00")
        sb.addPermanentWidget(self.app_session_time_label)
        self._app_session_seconds = 0
        self._app_session_timer = QTimer(self)
        self._app_session_timer.setInterval(1000)
        self._app_session_timer.timeout.connect(self._update_app_session_time)
        self._app_session_timer.start()

    def _set_initial_control_states(self):
        if self.top_ctrl:
            self.top_ctrl.update_connection_status("Disconnected", False)
        if hasattr(self, "start_recording_action"):
            self.start_recording_action.setEnabled(False)
        if hasattr(self, "stop_recording_action"):
            self.stop_recording_action.setEnabled(False)

        if self.camera_panel:  # This is your new tabbed CameraControlPanel
            self.camera_panel.setEnabled(
                False
            )  # Start disabled; enable it in _initialize_camera_on_startup if IC4 is ready
            # You might want to initially disable the "Adjustments" tab if its controls aren't active yet
            if (
                hasattr(self.camera_panel, "tab_widget")
                and self.camera_panel.tab_widget.count() > 1
            ):
                self.camera_panel.tab_widget.setTabEnabled(
                    1, False
                )  # Index 1 for "Adjustments" tab

    def _trigger_plot_reset_zoom_from_controls(self):
        """Slot to handle reset zoom request specifically from PlotControlPanel's button."""
        if (
            hasattr(self, "pressure_plot_widget")
            and self.pressure_plot_widget
            and hasattr(self.top_ctrl, "plot_controls")
            and self.top_ctrl.plot_controls
        ):

            auto_x = self.top_ctrl.plot_controls.auto_x_cb.isChecked()
            auto_y = self.top_ctrl.plot_controls.auto_y_cb.isChecked()

            self.pressure_plot_widget.reset_zoom(auto_x, auto_y)
            log.debug(
                f"Plot zoom reset triggered by button. AutoX: {auto_x}, AutoY: {auto_y}"
            )
        else:
            log.warning("Cannot reset plot zoom, required UI components missing.")

    @pyqtSlot(str)
    def _handle_serial_status_change(self, status: str):
        log.info(f"Serial status: {status}")
        self.statusBar().showMessage(f"PRIM Device: {status}", 4000)
        # Determine connected state more reliably
        connected = (
            "connected" in status.lower()
            or "opened serial port" in status.lower()
            or "simulation mode" in status.lower()
        )  # Simulation is also a "connected" state for UI

        if self.top_ctrl:
            self.top_ctrl.update_connection_status(status, connected)

        self.connect_serial_action.setIcon(
            self.icon_disconnect if connected else self.icon_connect
        )
        self.connect_serial_action.setText(
            f"{'Disconnect' if connected else 'Connect'} PRIM Device"
        )
        self.serial_port_combobox.setEnabled(not connected)

        if connected and self.pressure_plot_widget:
            self.pressure_plot_widget.clear_plot()  # Clear plot on new connection
            # Update placeholder if switching to simulation or real device
            if "simulation mode" in status.lower():
                self.pressure_plot_widget._update_placeholder(
                    "Waiting for PRIM device data (Simulation)..."
                )
            else:
                self.pressure_plot_widget._update_placeholder(
                    "Waiting for PRIM device data..."
                )

        if not connected and self._is_recording:
            # This implies a disconnection during recording
            QMessageBox.warning(
                self,
                "Recording Auto-Stopped",
                "PRIM device disconnected. Recording stopped.",
            )
            self._trigger_stop_recording()  # Stop recording if device disconnects

        self._update_recording_actions_enable_state()

    @pyqtSlot(str)
    def _handle_serial_error(self, msg: str):
        log.error(f"Serial error: {msg}")
        self.statusBar().showMessage(f"Serial Error: {msg}", 6000)
        # If the error implies disconnection, update status accordingly
        if (
            "disconnecting" in msg.lower()
            or "error opening" in msg.lower()
            or "serial error" in msg.lower()
        ):
            self._handle_serial_status_change(f"Error: {msg}. Disconnected.")
        self._update_recording_actions_enable_state()  # Re-evaluate recording actions

    @pyqtSlot()
    def _handle_serial_thread_finished(self):
        log.info("SerialThread 'finished' signal received.")
        sender = self.sender()

        # Check if the sender is the current _serial_thread instance
        if self._serial_thread is sender:
            current_conn_text = ""
            if self.top_ctrl and hasattr(self.top_ctrl, "conn_lbl"):
                # Check current displayed status to avoid redundant "Disconnected" messages
                # if the status was already set to an error or disconnected state.
                current_conn_text = self.top_ctrl.conn_lbl.text().lower()

            # Only update status if it wasn't already set to an error/disconnected state by _handle_serial_error or explicit stop
            if not (
                "error" in current_conn_text
                or "failed" in current_conn_text
                or "disconnected" in current_conn_text
            ):
                if (
                    "simulation" not in current_conn_text
                ):  # Don't show "Disconnected" if it was just simulation ending.
                    self._handle_serial_status_change("Disconnected")

            if self._serial_thread:  # Double check before deleteLater
                self._serial_thread.deleteLater()
            self._serial_thread = None
            log.info("Current _serial_thread instance cleaned up.")
        elif sender and isinstance(
            sender, SerialThread
        ):  # Check if it's an orphaned SerialThread
            log.warning(
                "Received 'finished' from an orphaned SerialThread instance. Cleaning it up."
            )
            sender.deleteLater()
        else:  # Should not happen
            log.warning(
                "Received 'finished' signal, but sender is not the expected SerialThread or is None."
            )

        self._update_recording_actions_enable_state()

    @pyqtSlot(int, float, float)
    def _handle_new_serial_data(self, idx: int, t: float, p: float):
        plot_ctrls = getattr(self.top_ctrl, "plot_controls", None)
        if plot_ctrls:  # Ensure plot_ctrls exists
            self.top_ctrl.update_prim_data(
                idx, t, p
            )  # Update labels in TopControlPanel
            if self.pressure_plot_widget:
                self.pressure_plot_widget.update_plot(
                    t,
                    p,
                    plot_ctrls.auto_x_cb.isChecked(),
                    plot_ctrls.auto_y_cb.isChecked(),
                )

        # Optional: Console logging for new data (can be verbose)
        # if self.dock_console and self.dock_console.isVisible() and self.console_out_textedit:
        #     self.console_out_textedit.append(f"PRIM Data: Idx={idx}, Time={t:.3f}s, P={p:.2f}")

        if self._is_recording and self._recording_worker:
            try:
                self._recording_worker.add_csv_data(t, idx, p)
            except Exception as e_csv:
                log.exception(f"Error adding CSV data to recording queue: {e_csv}")
                self.statusBar().showMessage(
                    "CRITICAL: Error queueing CSV data. Recording data may be lost.",
                    5000,
                )
                # Potentially stop recording or flag major error
                # self._trigger_stop_recording()

    def _toggle_serial_connection(self):
        if self._serial_thread and self._serial_thread.isRunning():
            log.info("User requested to stop serial connection.")
            self._serial_thread.stop()  # stop() in SerialThread should set self.running = False
            # The finished signal from SerialThread will handle cleanup.
        else:
            # Get selected port from combobox
            selected_index = self.serial_port_combobox.currentIndex()
            port_to_use_variant = self.serial_port_combobox.itemData(selected_index)
            port_to_use = (
                port_to_use_variant if isinstance(port_to_use_variant, str) else None
            )  # Ensure it's a string or None

            current_text = self.serial_port_combobox.currentText()
            is_simulation = "simulated data" in current_text.lower()

            if not port_to_use and not is_simulation:
                QMessageBox.warning(
                    self,
                    "Serial Connection Error",
                    "Please select a valid serial port or choose 'Simulated Data'.",
                )
                return

            log.info(
                f"User requested to start serial connection: Port='{port_to_use if port_to_use else 'Simulation'}'"
            )

            # Cleanup old thread instance if it exists (e.g., from a previous failed start)
            if self._serial_thread:
                log.debug(
                    "Cleaning up previous _serial_thread instance before starting new one."
                )
                if (
                    self._serial_thread.isRunning()
                ):  # Should not happen if logic is correct, but as a safeguard
                    self._serial_thread.stop()
                    self._serial_thread.wait(500)  # Brief wait
                self._serial_thread.deleteLater()
                self._serial_thread = None
                QApplication.processEvents()

            try:
                self._serial_thread = SerialThread(
                    port=port_to_use, parent=self
                )  # Pass parent for auto-cleanup
                # Connect signals
                self._serial_thread.data_ready.connect(self._handle_new_serial_data)
                self._serial_thread.error_occurred.connect(self._handle_serial_error)
                self._serial_thread.status_changed.connect(
                    self._handle_serial_status_change
                )
                self._serial_thread.finished.connect(
                    self._handle_serial_thread_finished
                )

                self._serial_thread.start()  # Start the thread
            except Exception as e:
                log.exception("Failed to create or start SerialThread.")
                QMessageBox.critical(
                    self,
                    "Serial Thread Error",
                    f"Could not start serial communication: {e}",
                )
                if (
                    self._serial_thread
                ):  # If instance was created but start failed or other error
                    self._serial_thread.deleteLater()
                    self._serial_thread = None
                self._update_recording_actions_enable_state()  # Ensure UI reflects failure

    def _update_recording_actions_enable_state(self):
        # Recording can start if serial is ready (connected or simulating) AND not already recording
        serial_ready_for_recording = (
            self._serial_thread is not None
            and self._serial_thread.isRunning()
            and (
                "connected" in self.top_ctrl.conn_lbl.text().lower()
                or "simulation mode" in self.top_ctrl.conn_lbl.text().lower()
                or "opened serial port" in self.top_ctrl.conn_lbl.text().lower()
            )
        )

        can_start_recording = serial_ready_for_recording and not self._is_recording
        can_stop_recording = self._is_recording  # Can only stop if currently recording

        if hasattr(self, "start_recording_action"):
            self.start_recording_action.setEnabled(can_start_recording)
        if hasattr(self, "stop_recording_action"):
            self.stop_recording_action.setEnabled(can_stop_recording)

    def _trigger_start_recording_dialog(self):
        # Check if serial connection is active (real or simulated)
        serial_is_active = (
            self._serial_thread
            and self._serial_thread.isRunning()
            and (
                "connected" in self.top_ctrl.conn_lbl.text().lower()
                or "simulation mode" in self.top_ctrl.conn_lbl.text().lower()
                or "opened serial port" in self.top_ctrl.conn_lbl.text().lower()
            )
        )

        if not serial_is_active:
            QMessageBox.warning(
                self,
                "Cannot Start Recording",
                "PRIM device (or simulation) is not active.",
            )
            return
        if self._is_recording:
            QMessageBox.information(
                self,
                "Recording Already Active",
                "A recording session is already in progress.",
            )
            return

        # --- Recording Dialog ---
        dialog = QDialog(self)
        dialog.setWindowTitle("New Recording Session Details")
        layout = QFormLayout(dialog)

        # Session Name
        default_session_name = (
            f"Session_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}"
        )
        name_edit = QLineEdit(default_session_name)
        name_edit.setPlaceholderText("Enter a unique session name")
        layout.addRow("Session Name:", name_edit)

        # Operator
        operator_edit = QLineEdit(
            load_app_setting("last_operator", "")
        )  # Load last used operator
        operator_edit.setPlaceholderText("Operator's name/initials")
        layout.addRow("Operator:", operator_edit)

        # Notes
        notes_edit = QTextEdit()
        notes_edit.setPlaceholderText("Optional notes about the session...")
        notes_edit.setFixedHeight(80)  # Reasonable default height
        layout.addRow("Notes:", notes_edit)

        # Dialog Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec_() != QDialog.Accepted:
            log.info("Recording dialog cancelled by user.")
            return

        # --- Process Dialog Input ---
        save_app_setting(
            "last_operator", operator_edit.text()
        )  # Save operator for next time

        session_name_raw = name_edit.text().strip()
        if not session_name_raw:  # Use placeholder if empty
            session_name_raw = (
                name_edit.placeholderText()
                if name_edit.placeholderText()
                else default_session_name
            )

        # Sanitize session name for folder/file usage
        session_name_safe = "".join(
            c if c.isalnum() or c in ("_", "-") else "_" for c in session_name_raw
        )
        session_name_safe = re.sub(r"_+", "_", session_name_safe).strip(
            "_"
        )  # Replace multiple underscores and strip leading/trailing
        if not session_name_safe:  # Fallback if sanitization results in empty string
            session_name_safe = f"Session_Unnamed_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}"

        # --- Create Session Folder and Define Paths ---
        session_folder = os.path.join(PRIM_RESULTS_DIR, session_name_safe)
        try:
            os.makedirs(session_folder, exist_ok=True)
            log.info(f"Session folder created/ensured: {session_folder}")
        except OSError as e_mkdir:
            log.error(f"Failed to create session folder '{session_folder}': {e_mkdir}")
            QMessageBox.critical(
                self,
                "File System Error",
                f"Could not create session folder:\n{e_mkdir}",
            )
            return

        # Base path for recording files (video, CSV) without extension
        recording_base_prefix = os.path.join(session_folder, session_name_safe)
        self.last_trial_basepath = session_folder  # Store parent folder for later access (e.g., saving plot data)

        # --- Determine Recording Parameters (FPS, Frame Size) ---
        # For simplified camera, we might not have reliable dynamic frame size/fps from camera settings yet.
        # Using defaults from config.py, but ideally, this would come from an active (even if simplified) camera stream.
        # For now, assume we don't have live camera parameters for recording.
        # This part will need adjustment once simplified camera feed is stable and provides frame info.

        w, h = DEFAULT_FRAME_SIZE  # Fallback
        record_fps = DEFAULT_FPS  # Fallback

        log.warning(
            "Using default frame size and FPS for recording as simplified camera does not yet provide this. Video may not match live view if camera defaults differ."
        )
        # TODO: Once basic live feed is working, get frame dimensions from the received frames for the recorder.
        # Example: if self.camera_view and self.camera_view.current_frame_width > 0:
        # w, h = self.camera_view.current_frame_width, self.camera_view.current_frame_height
        # record_fps = self.camera_thread.target_fps # Or a fixed value if target_fps isn't reliable yet

        video_ext = DEFAULT_VIDEO_EXTENSION.lower()
        codec = DEFAULT_VIDEO_CODEC
        log.info(
            f"Preparing to start recording: Session='{session_name_safe}'. Target Params: FPS={record_fps}, Size={w}x{h}, Format={video_ext}/{codec}"
        )

        # --- Start Recording Worker ---
        try:
            # Ensure any previous worker is stopped and cleaned up
            if self._recording_worker and self._recording_worker.isRunning():
                log.info("Stopping previous recording worker before starting new one.")
                self._recording_worker.stop_worker()
                if not self._recording_worker.wait(2000):  # Wait for graceful stop
                    log.warning(
                        "Previous recording worker did not stop gracefully, terminating."
                    )
                    self._recording_worker.terminate()
                    self._recording_worker.wait(500)
            if self._recording_worker:
                self._recording_worker.deleteLater()
                self._recording_worker = None
                QApplication.processEvents()

            self._recording_worker = RecordingWorker(
                basepath=recording_base_prefix,
                fps=record_fps,
                frame_size=(w, h),
                video_ext=video_ext,
                video_codec=codec,
                parent=self,  # For Qt parent-child cleanup
            )
            self._recording_worker.start()

            # Wait a bit for the worker to initialize its internal TrialRecorder
            # A more robust way would be a signal from RecordingWorker once it's truly ready.
            QThread.msleep(700)  # Increased sleep for robustness

            if not (
                self._recording_worker
                and self._recording_worker.isRunning()
                and self._recording_worker.is_ready_to_record  # Crucial check
            ):
                log.error(
                    "RecordingWorker started but did not report as ready (is_ready_to_record is false)."
                )
                # Attempt to get more detailed error if TrialRecorder init failed (this is complex)
                # For now, a generic error.
                raise RuntimeError(
                    "Recording worker or its internal TrialRecorder failed readiness check. Check logs for TrialRecorder errors."
                )

            self._is_recording = True
            if hasattr(self, "start_recording_action"):
                self.start_recording_action.setIcon(
                    self.icon_recording_active
                )  # Update icon
            self._update_recording_actions_enable_state()  # Update button states

            if self.pressure_plot_widget:
                self.pressure_plot_widget.clear_plot()  # Clear plot for new recording session

            self.statusBar().showMessage(
                f"🔴 REC: {session_name_safe}", 0  # Persistent message (0 timeout)
            )
            log.info(f"Recording started successfully for session: {session_name_safe}")

        except Exception as e_rec_start:
            log.exception(
                f"Critical error during recording start sequence: {e_rec_start}"
            )
            QMessageBox.critical(
                self,
                "Recording Start Error",
                f"Could not start recording worker:\n{e_rec_start}",
            )
            if self._recording_worker:  # Cleanup if worker was created but failed
                if self._recording_worker.isRunning():
                    self._recording_worker.stop_worker()
                    self._recording_worker.wait(500)
                self._recording_worker.deleteLater()
                self._recording_worker = None
            self._is_recording = False
            self._update_recording_actions_enable_state()  # Reset UI
            if self.statusBar().currentMessage().startswith("🔴 REC:"):
                self.statusBar().clearMessage()
            return

    def _trigger_stop_recording(self):
        if not self._is_recording or not self._recording_worker:
            log.info(
                "Stop recording called, but not currently recording or worker is missing."
            )
            if self._is_recording:  # If flag is somehow true without worker, reset it
                self._is_recording = False
            self._update_recording_actions_enable_state()
            if self.statusBar().currentMessage().startswith("🔴 REC:"):
                self.statusBar().clearMessage()
            return

        log.info("User requested to stop recording...")
        # Determine session name for messages (safer access)
        session_name_stopped = "Session"  # Default
        if hasattr(self, "last_trial_basepath") and self.last_trial_basepath:
            # Extract from the folder name, which should be the sanitized session name
            base_folder_name = os.path.basename(self.last_trial_basepath)
            if base_folder_name:  # Ensure it's not empty
                session_name_stopped = base_folder_name

        try:
            # Signal the worker to stop and wait for it to finish processing its queue
            self._recording_worker.stop_worker()  # This queues a 'stop' sentinel
            log.debug(
                "Waiting for RecordingWorker to finish processing queue and stop..."
            )
            if not self._recording_worker.wait(
                10000
            ):  # Increased timeout for potentially large queues
                log.warning(
                    "RecordingWorker did not stop gracefully within timeout, terminating."
                )
                self._recording_worker.terminate()  # Force terminate if unresponsive
                self._recording_worker.wait(1000)  # Wait for termination to complete
            log.info("RecordingWorker thread has finished or been terminated.")

            # Get final frame count (safer access)
            count = 0
            if hasattr(
                self._recording_worker, "video_frame_count"
            ):  # Check if property exists
                count = self._recording_worker.video_frame_count

            self.statusBar().showMessage(
                f"Recording '{session_name_stopped}' stopped. {count} video frames recorded.",
                7000,
            )

            # Auto-save plot data for the session that just ended
            if hasattr(self, "last_trial_basepath") and self.last_trial_basepath:
                self._save_current_plot_data_for_session()  # Save plot data

                # Ask user if they want to open the folder
                if (
                    QMessageBox.information(
                        self,
                        "Recording Saved",
                        f"Session '{session_name_stopped}' data saved to:\n{self.last_trial_basepath}\n\nVideo frames recorded: {count}\n\nOpen session folder?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No,  # Default to No
                    )
                    == QMessageBox.Yes
                ):
                    try:
                        if sys.platform == "win32":
                            os.startfile(self.last_trial_basepath)
                        elif sys.platform == "darwin":  # macOS
                            os.system(f'open "{self.last_trial_basepath}"')
                        else:  # Linux and other POSIX
                            os.system(f'xdg-open "{self.last_trial_basepath}"')
                    except Exception as e_open:
                        log.error(
                            f"Error opening session folder '{self.last_trial_basepath}': {e_open}"
                        )
                        QMessageBox.warning(
                            self,
                            "Open Folder Error",
                            f"Could not open folder:\n{e_open}",
                        )
            else:
                QMessageBox.information(
                    self,
                    "Recording Stopped",
                    f"{count} video frames recorded. Path information was missing for auto-save features.",
                )

        except Exception as e_stop_rec:
            log.exception(
                f"Error during user-initiated stop recording sequence: {e_stop_rec}"
            )
            self.statusBar().showMessage(
                f"Error stopping recording: {e_stop_rec}", 5000
            )
        finally:
            # Cleanup worker instance
            if self._recording_worker:
                self._recording_worker.deleteLater()  # Schedule for deletion
            self._recording_worker = None
            self._is_recording = False  # Crucial: reset recording flag

            if hasattr(self, "start_recording_action"):
                self.start_recording_action.setIcon(
                    self.icon_record_start
                )  # Reset icon

            self._update_recording_actions_enable_state()  # Update UI button states

            if self.statusBar().currentMessage().startswith("🔴 REC:"):
                self.statusBar().clearMessage()  # Clear persistent recording message
            log.info("Recording fully stopped and UI updated.")

    def _save_current_plot_data_for_session(self):
        if not hasattr(self, "last_trial_basepath") or not self.last_trial_basepath:
            log.warning("Cannot auto-save plot data: 'last_trial_basepath' is not set.")
            return
        if not (
            self.pressure_plot_widget
            and self.pressure_plot_widget.times
            and self.pressure_plot_widget.pressures
        ):
            log.info("No plot data available to auto-save for the session.")
            return

        # Determine session name from the folder path for the CSV filename
        session_name_for_file = os.path.basename(self.last_trial_basepath)
        if not session_name_for_file:  # Fallback if base path itself is odd
            session_name_for_file = "session_plot"

        csv_filename = f"{session_name_for_file}_pressure_plot_data.csv"
        csv_path = os.path.join(self.last_trial_basepath, csv_filename)

        try:
            with open(csv_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["time_s", "pressure_mmHg"])  # Header
                for t, p in zip(
                    self.pressure_plot_widget.times, self.pressure_plot_widget.pressures
                ):
                    writer.writerow(
                        [f"{t:.6f}", f"{p:.6f}"]
                    )  # Format to 6 decimal places
            log.info(f"Session plot data automatically saved to: {csv_path}")
            self.statusBar().showMessage(
                f"Plot CSV for session '{session_name_for_file}' saved.", 4000
            )
        except Exception as e_save_plot:
            log.exception(
                f"Failed to auto-save session plot data to '{csv_path}': {e_save_plot}"
            )
            QMessageBox.warning(
                self,
                "Plot Data Save Error",
                f"Could not automatically save plot CSV data:\n{e_save_plot}",
            )

    @pyqtSlot()
    def _clear_pressure_plot(self):
        if self.pressure_plot_widget:
            self.pressure_plot_widget.clear_plot()
            self.statusBar().showMessage("Pressure plot data cleared.", 3000)

    @pyqtSlot()
    def _export_plot_data_as_csv(self):
        if not (
            self.pressure_plot_widget
            and self.pressure_plot_widget.times
            and self.pressure_plot_widget.pressures
        ):
            QMessageBox.information(
                self, "No Data to Export", "The pressure plot has no data to export."
            )
            return

        default_filename = f"manual_plot_export_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Plot Data as CSV", default_filename, "CSV Files (*.csv)"
        )
        if not path:  # User cancelled
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
                f"Plot data successfully exported to {os.path.basename(path)}", 4000
            )
            log.info(f"Plot data manually exported to: {path}")
        except Exception as e_export:
            log.exception(
                f"Failed to manually export plot data to '{path}': {e_export}"
            )
            QMessageBox.critical(
                self, "Export Error", f"Could not save plot CSV data:\n{e_export}"
            )

    @pyqtSlot()
    def _show_about_dialog(self):
        QMessageBox.about(self, f"About {APP_NAME}", ABOUT_TEXT)

    def _update_app_session_time(self):
        self._app_session_seconds += 1
        h, rem = divmod(self._app_session_seconds, 3600)
        m, s = divmod(rem, 60)
        self.app_session_time_label.setText(f"Session: {h:02}:{m:02}:{s:02}")

    @pyqtSlot(str, str)
    def _on_camera_error(self, msg: str, code: str):
        full_msg = f"Camera Error: {msg}" + (
            f" (SDK Code: {code})" if code and code != "None" else ""
        )
        log.error(full_msg)
        QMessageBox.critical(self, "Camera Runtime Error", full_msg)

        # Stop and clean up the camera thread if it exists and is running
        if self.camera_thread:
            if self.camera_thread.isRunning():
                try:
                    log.info("Stopping camera thread due to reported error...")
                    self.camera_thread.stop()  # stop() in SDKCameraThread includes wait()
                except Exception as e_stop_cam_err:
                    log.error(
                        f"Error trying to stop camera thread after it reported an error: {e_stop_cam_err}"
                    )
            self.camera_thread.deleteLater()  # Schedule for deletion
            self.camera_thread = None

        if self.camera_panel:
            self.camera_panel.setEnabled(False)  # Disable controls
        self.statusBar().showMessage(
            "Camera Error! Live feed stopped or failed to start.",
            0,  # Persistent message
        )
        # If recording depends on camera, might need to stop recording too
        if self._is_recording and self._recording_worker:
            log.warning(
                "Camera error occurred during active recording. Stopping recording."
            )
            # Consider if a more specific message is needed for recording stop due to camera error
            self._trigger_stop_recording()

    def closeEvent(self, event):
        log.info("MainWindow closeEvent triggered.")

        # Handle active recording session
        if self._is_recording:
            reply = QMessageBox.question(
                self,
                "Confirm Exit While Recording",
                "A recording session is currently active. Are you sure you want to stop recording and exit?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,  # Default to No
            )
            if reply == QMessageBox.Yes:
                log.info("User chose to stop recording and exit.")
                self._trigger_stop_recording()  # This will attempt to save data and clean up the worker
                # Wait for the recording worker to actually finish after _trigger_stop_recording
                if self._recording_worker and not self._recording_worker.wait(
                    5000
                ):  # Give it time
                    log.warning(
                        "Recording worker did not finish cleanly during app close. Forcing cleanup."
                    )
                    # _trigger_stop_recording should have set self._recording_worker to None if successful
            else:
                log.info("User cancelled exit due to active recording.")
                event.ignore()  # Prevent window from closing
                return

        # Gracefully stop all threads
        threads_to_clean = [
            (
                "CameraThread",
                self.camera_thread,
                (
                    getattr(self.camera_thread, "stop", None)
                    if self.camera_thread
                    else None
                ),
            ),
            (
                "SerialThread",
                self._serial_thread,
                (
                    getattr(self._serial_thread, "stop", None)
                    if self._serial_thread
                    else None
                ),
            ),
            # Recording worker should have been handled by the block above if recording was active.
            # If it wasn't active, or if _trigger_stop_recording failed to nullify it, handle here.
            (
                "RecordingWorker",
                self._recording_worker,
                (
                    getattr(self._recording_worker, "stop_worker", None)
                    if self._recording_worker
                    else None
                ),
            ),
        ]

        for name, thread_instance, stop_method in threads_to_clean:
            if thread_instance:  # Check if instance exists
                if thread_instance.isRunning():
                    log.info(
                        f"Stopping {name} ({thread_instance.__class__.__name__}) on application close..."
                    )
                    if stop_method:
                        try:
                            stop_method()
                            # Wait for the thread to finish. Adjust timeout as necessary.
                            wait_timeout = 3000 if name == "RecordingWorker" else 1500
                            if not thread_instance.wait(wait_timeout):
                                log.warning(
                                    f"{name} ({thread_instance.__class__.__name__}) did not stop gracefully, terminating."
                                )
                                thread_instance.terminate()  # Force terminate if unresponsive
                                thread_instance.wait(500)  # Brief wait for termination
                        except Exception as e_stop_final:
                            log.error(
                                f"Exception while stopping {name} during close: {e_stop_final}"
                            )
                    else:  # No stop method, or it's None
                        log.warning(
                            f"No standard stop method found for {name}, attempting terminate if running."
                        )
                        thread_instance.terminate()
                        thread_instance.wait(500)

                thread_instance.deleteLater()  # Schedule for Qt's event loop to delete
                # Set the attribute to None to reflect cleanup
                if name == "CameraThread":
                    self.camera_thread = None
                elif name == "SerialThread":
                    self._serial_thread = None
                elif name == "RecordingWorker":
                    self._recording_worker = None
            else:
                log.debug(f"Thread {name} was already None or cleaned up.")

        QApplication.processEvents()  # Allow Qt to process deleteLater events

        log.info(
            "All threads processed for cleanup. Proceeding with application close."
        )
        super().closeEvent(event)
