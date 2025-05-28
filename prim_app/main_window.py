# PRIM-QTAPP/prim_app/main_window.py
import os
import sys
import re
import logging
import csv
import json
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
from PyQt5.QtCore import Qt, pyqtSlot, QTimer, QVariant, QDateTime, QSize, QThread
from PyQt5.QtGui import QIcon, QKeySequence

import prim_app
from prim_app import initialize_ic4_with_cti, is_ic4_fully_initialized
import imagingcontrol4 as ic4

from utils.app_settings import (
    save_app_setting,
    load_app_setting,
    SETTING_CTI_PATH,
    SETTING_LAST_CAMERA_SERIAL,
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
    AVAILABLE_RESOLUTIONS,  # Added AVAILABLE_RESOLUTIONS
)

from ui.control_panels.top_control_panel import TopControlPanel
from ui.control_panels.camera_control_panel import CameraControlPanel
from ui.canvas.gl_viewfinder import GLViewfinder
from ui.canvas.pressure_plot_widget import PressurePlotWidget
from threads.sdk_camera_thread import SDKCameraThread
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
        self.camera_panel = None  # This is CameraControlPanel instance
        self.camera_view = None
        self.bottom_split = None
        self.camera_settings = {}  # Holds current camera model, serial etc.

        self._init_paths_and_icons()
        self._build_console_log_dock()
        self._build_central_widget_layout()  # camera_panel is created here
        self._build_menus()
        self._build_main_toolbar()
        self._build_status_bar()

        # Connections for TopControlPanel (plot controls)
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
                self.camera_panel.setEnabled(
                    False
                )  # Keep panel disabled until SDK is ready
                self.camera_panel.disable_controls_initially()

        QTimer.singleShot(50, self._set_initial_splitter_sizes)
        self._set_initial_control_states()  # This will disable camera panel further
        log.info("MainWindow initialized.")
        self.showMaximized()

    def _set_initial_splitter_sizes(self):
        if self.bottom_split and self.bottom_split.count() == 2:
            QTimer.singleShot(100, self._perform_splitter_sizing)

    def _perform_splitter_sizing(self):
        if self.bottom_split and self.bottom_split.count() == 2:
            w = self.bottom_split.width()
            h = self.bottom_split.height()
            if w > 0 and h > 0:
                self.bottom_split.setSizes([int(w * 0.65), int(w * 0.35)])
                log.debug(f"Splitter sizes set for width {w}")
            else:
                log.warning("Bottom splitter not ready for sizing after delay.")

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
                    # save_app_setting(SETTING_CTI_PATH, cti) # initialize_ic4_with_cti now handles this
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
                    self.camera_panel.disable_controls_initially()
        elif is_ic4_fully_initialized():
            self.statusBar().showMessage(
                f"IC4 initialized with CTI: {os.path.basename(load_app_setting(SETTING_CTI_PATH, ''))}",
                5000,
            )

    def _connect_camera_signals(self):
        th = self.camera_thread
        cp = self.camera_panel  # This is the CameraControlPanel instance

        if not (th and self.camera_view and cp):
            log.warning(
                "Cannot connect camera signals: missing components (thread, view, or panel)."
            )
            return True  # Indicate failure to connect

        # --- SDKCameraThread -> MainWindow/CameraView/CameraControlPanel ---
        try:  # Disconnect first to avoid multiple connections if called again
            th.frame_ready.disconnect(self.camera_view.update_frame)
            th.camera_error.disconnect(self._on_camera_error)
            th.camera_info_updated.disconnect(self._update_camera_status_tab)
            th.exposure_params_updated.disconnect(self._update_camera_exposure_controls)
            th.gain_params_updated.disconnect(self._update_camera_gain_controls)
            th.fps_params_updated.disconnect(self._update_camera_fps_controls)
            th.pixel_format_options_updated.disconnect(
                self._update_camera_pixel_format_options
            )
            th.resolution_params_updated.disconnect(
                self._update_camera_resolution_params
            )
        except TypeError:  # Thrown if a signal was not connected
            pass
        except Exception as e:
            log.error(f"Error during signal disconnection: {e}")

        th.frame_ready.connect(self.camera_view.update_frame)
        th.camera_error.connect(self._on_camera_error)

        # SDK Info/Params -> MainWindow (slots) -> CameraControlPanel (UI update methods)
        th.camera_info_updated.connect(self._update_camera_status_tab)
        th.exposure_params_updated.connect(self._update_camera_exposure_controls)
        th.gain_params_updated.connect(self._update_camera_gain_controls)
        th.fps_params_updated.connect(self._update_camera_fps_controls)
        th.pixel_format_options_updated.connect(
            self._update_camera_pixel_format_options
        )
        th.resolution_params_updated.connect(self._update_camera_resolution_params)

        # --- CameraControlPanel UI changes -> SDKCameraThread control slots ---
        try:  # Disconnect first
            cp.auto_exposure_toggled.disconnect(th.set_exposure_auto)
            cp.exposure_changed.disconnect(th.set_exposure_time)
            cp.gain_changed.disconnect(th.set_gain)
            cp.fps_changed.disconnect(th.set_fps)
            cp.pixel_format_changed.disconnect(th.set_pixel_format)
            cp.resolution_changed.disconnect(th.set_resolution_from_string)
            cp.start_stream_requested.disconnect(self._on_start_live_button_pressed)
            cp.stop_stream_requested.disconnect(self._on_stop_live_button_pressed)
        except TypeError:
            pass
        except Exception as e:
            log.error(f"Error during control signal disconnection: {e}")

        cp.auto_exposure_toggled.connect(th.set_exposure_auto)
        cp.exposure_changed.connect(th.set_exposure_time)
        cp.gain_changed.connect(th.set_gain)
        cp.fps_changed.connect(th.set_fps)
        cp.pixel_format_changed.connect(th.set_pixel_format)
        cp.resolution_changed.connect(th.set_resolution_from_string)

        cp.start_stream_requested.connect(self._on_start_live_button_pressed)
        cp.stop_stream_requested.connect(self._on_stop_live_button_pressed)

        log.info("Camera signals connected.")
        return False  # Indicate success

    # --- Slots in MainWindow to receive updates from SDKCameraThread and forward to CameraControlPanel ---
    @pyqtSlot(dict)
    def _update_camera_status_tab(self, info: dict):
        if self.camera_panel:
            self.camera_panel.update_status_info(info)

    @pyqtSlot(dict)
    def _update_camera_exposure_controls(self, params: dict):
        if self.camera_panel:
            self.camera_panel.set_exposure_params(params)
            # Enable adjustment tab if exposure params are available (implies camera is somewhat responsive)
            if hasattr(self.camera_panel, "enable_adjustment_controls"):
                self.camera_panel.enable_adjustment_controls(True)

    @pyqtSlot(dict)
    def _update_camera_gain_controls(self, params: dict):
        if self.camera_panel:
            self.camera_panel.set_gain_params(params)

    @pyqtSlot(dict)
    def _update_camera_fps_controls(self, params: dict):
        if self.camera_panel:
            self.camera_panel.set_fps_params(params)

    @pyqtSlot(list, str)
    def _update_camera_pixel_format_options(self, options: list, current_format: str):
        if self.camera_panel:
            self.camera_panel.populate_pixel_formats(options, current_format)

    @pyqtSlot(dict)
    def _update_camera_resolution_params(self, params: dict):
        # params: {w_min, w_max, w_curr, w_inc, h_min, h_max, h_curr, h_inc, w_writable, h_writable}
        if self.camera_panel:
            max_w_cam = params.get("w_max", 0)
            max_h_cam = params.get("h_max", 0)
            curr_w_cam = params.get("w_curr", 0)
            curr_h_cam = params.get("h_curr", 0)

            filtered_resolutions = []
            if (
                max_w_cam > 0 and max_h_cam > 0
            ):  # Only filter if we have valid max dimensions
                for res_str in AVAILABLE_RESOLUTIONS:  # From config.py
                    try:
                        w, h = map(int, res_str.split("x"))
                        if w <= max_w_cam and h <= max_h_cam:
                            filtered_resolutions.append(res_str)
                    except ValueError:
                        log.warning(
                            f"Malformed resolution string in AVAILABLE_RESOLUTIONS: {res_str}"
                        )
                        continue
            else:  # If camera doesn't report max W/H, use the full list from config
                log.warning(
                    "Camera did not report max Width/Height, using full AVAILABLE_RESOLUTIONS list."
                )
                filtered_resolutions = list(AVAILABLE_RESOLUTIONS)  # Make a copy

            current_res_str_cam = (
                f"{curr_w_cam}x{curr_h_cam}"
                if curr_w_cam > 0 and curr_h_cam > 0
                else ""
            )

            if (
                current_res_str_cam
                and current_res_str_cam not in filtered_resolutions
                and curr_w_cam > 0
            ):
                filtered_resolutions.append(current_res_str_cam)
                # Sort resolutions for better UX, perhaps numerically by width then height
                try:
                    filtered_resolutions.sort(
                        key=lambda r: (int(r.split("x")[0]), int(r.split("x")[1]))
                    )
                except:  # Fallback if sorting fails (e.g. "N/A" string)
                    pass

            self.camera_panel.populate_resolutions(
                filtered_resolutions, current_res_str_cam
            )

            # Enable/disable the resolution combo based on writability of Width or Height
            can_change_resolution = params.get("w_writable", False) or params.get(
                "h_writable", False
            )
            self.camera_panel.res_combo.setEnabled(
                can_change_resolution and bool(filtered_resolutions)
            )

    def _start_sdk_camera_thread(
        self, camera_identifier, fps_target, initial_settings=None
    ):
        if self.camera_thread and self.camera_thread.isRunning():
            log.info("Stopping existing camera thread before starting a new one.")
            self.camera_thread.stop()
            # self.camera_thread.deleteLater() # Defer deletion until it's truly finished via finished signal
            # self.camera_thread = None
            # QApplication.processEvents()
            # Let the finished signal handle cleanup to avoid race conditions.
            # Forcing a new start implies the old one should be gone or will be soon.

        log.info(
            f"Creating SDKCameraThread for '{camera_identifier}' with target FPS: {fps_target}"
        )
        self.camera_thread = SDKCameraThread(
            device_name=camera_identifier,
            fps=float(fps_target),
            parent=self,  # Parent for auto-cleanup if MW closes
        )
        # Connect finished signal for cleanup
        self.camera_thread.finished.connect(self._handle_camera_thread_finished)

        self.camera_settings["cameraSerialPattern"] = camera_identifier

        if self._connect_camera_signals():
            log.error("Failed to connect camera signals. Camera thread will not start.")
            if self.camera_panel:
                self.camera_panel.setEnabled(False)  # Ensure panel is disabled
                self.camera_panel.disable_controls_initially()
            if self.camera_thread:  # Clean up instance if connections failed
                self.camera_thread.deleteLater()
                self.camera_thread = None
            return

        self.camera_thread.start()
        self.statusBar().showMessage(f"Attempting live feed: {camera_identifier}", 5000)
        if self.camera_panel:
            self.camera_panel.setEnabled(True)
            self.camera_panel.start_btn.setEnabled(False)
            self.camera_panel.stop_btn.setEnabled(True)
            # Adjustment tab enablement is handled by _update_camera_exposure_controls or similar later

    @pyqtSlot()
    def _handle_camera_thread_finished(self):
        log.info("SDKCameraThread 'finished' signal received.")
        sender = self.sender()
        if self.camera_thread is sender:
            log.info("Current SDKCameraThread instance has finished.")
            # self.camera_thread.deleteLater() # Schedule for deletion by Qt's event loop
            self.camera_thread = None  # Clear the reference

            # Update UI to reflect that camera is no longer running
            if self.camera_panel:
                self.camera_panel.setEnabled(
                    True
                )  # Keep panel enabled to allow restart
                self.camera_panel.start_btn.setEnabled(True)
                self.camera_panel.stop_btn.setEnabled(False)
                if hasattr(self.camera_panel, "enable_adjustment_controls"):
                    self.camera_panel.enable_adjustment_controls(
                        False
                    )  # Disable adjustments tab
                # Optionally clear status fields or show "Disconnected"
                self.camera_panel.update_status_info()  # Clears to N/A

            if self.statusBar().currentMessage().startswith(
                "Attempting live feed"
            ) or self.statusBar().currentMessage().startswith(
                self.camera_settings.get("cameraIdentifier", "")
            ):
                self.statusBar().showMessage("Camera feed stopped.", 3000)
        elif sender and isinstance(sender, SDKCameraThread):
            log.warning(
                "Received 'finished' from an orphaned SDKCameraThread instance. Scheduling for deletion."
            )
            sender.deleteLater()

    def _initialize_camera_on_startup(self):
        if not is_ic4_fully_initialized():
            log.info(
                "IC4 not fully initialized on startup. Camera panel remains disabled."
            )
            self.statusBar().showMessage(
                "IC4 SDK not configured. Use Camera menu...", 5000
            )
            if self.camera_panel:
                self.camera_panel.setEnabled(False)
                self.camera_panel.disable_controls_initially()
            return

        log.info("Attempting to get IC4 camera...")
        if self.camera_panel:
            self.camera_panel.setEnabled(False)
            self.camera_panel.disable_controls_initially()

        available_devices = []
        try:
            available_devices = ic4.DeviceEnum.devices()
            if not available_devices:
                log.warning("No IC4 devices found.")
                self.statusBar().showMessage("No cameras found.", 5000)
                # Keep camera_panel disabled, but allow CTI change etc.
                if self.camera_panel:
                    self.camera_panel.setEnabled(True)
                    self.camera_panel.start_btn.setEnabled(True)
                return
        except Exception as e:
            log.error(f"Error enumerating IC4 devices: {e}")
            self.statusBar().showMessage(f"Error enumerating devices: {e}", 5000)
            if self.camera_panel:
                self.camera_panel.setEnabled(True)
                self.camera_panel.start_btn.setEnabled(True)
            return

        last_cam_id = load_app_setting(SETTING_LAST_CAMERA_SERIAL)
        device_to_use_info = None

        if last_cam_id:
            for dev_info in available_devices:
                if last_cam_id in (
                    getattr(dev_info, "serial", ""),
                    getattr(dev_info, "unique_name", ""),
                    getattr(dev_info, "model_name", ""),
                ):
                    device_to_use_info = dev_info
                    log.info(f"Found last used camera: {last_cam_id}")
                    break

        if not device_to_use_info:
            device_to_use_info = available_devices[0]
            log.info(
                "Using first available camera as last used not found or not specified."
            )

        camera_model_name = getattr(device_to_use_info, "model_name", "Unknown Model")
        camera_serial_number = getattr(device_to_use_info, "serial", "N/A")
        camera_unique_name = getattr(device_to_use_info, "unique_name", "")

        camera_identifier = (
            camera_serial_number
            if camera_serial_number and camera_serial_number != "N/A"
            else camera_unique_name if camera_unique_name else camera_model_name
        )

        if not camera_identifier:
            log.error(
                f"Could not obtain a valid identifier for camera: {device_to_use_info}"
            )
            self.statusBar().showMessage(f"Could not ID camera.", 5000)
            if self.camera_panel:
                self.camera_panel.setEnabled(True)
                self.camera_panel.start_btn.setEnabled(True)
            return

        log.info(
            f"Selected camera for startup: {camera_model_name} (ID used: {camera_identifier})."
        )
        self.camera_settings["cameraModel"] = camera_model_name
        self.camera_settings["cameraSerial"] = camera_serial_number
        self.camera_settings["cameraIdentifier"] = camera_identifier

        try:
            self._start_sdk_camera_thread(
                camera_identifier, DEFAULT_FPS
            )  # Pass initial target FPS
            save_app_setting(SETTING_LAST_CAMERA_SERIAL, camera_identifier)
        except Exception as e:
            log.exception(
                f"Failed to start camera '{camera_model_name}' on startup: {e}"
            )
            QMessageBox.critical(
                self, "Camera Start Error", f"Could not start {camera_model_name}:\n{e}"
            )
            if self.camera_panel:
                self.camera_panel.setEnabled(True)
                self.camera_panel.start_btn.setEnabled(True)

    def _set_initial_control_states(self):
        if self.top_ctrl:
            self.top_ctrl.update_connection_status("Disconnected", False)
        if hasattr(self, "start_recording_action"):
            self.start_recording_action.setEnabled(False)
        if hasattr(self, "stop_recording_action"):
            self.stop_recording_action.setEnabled(False)

        if self.camera_panel:
            self.camera_panel.setEnabled(False)
            self.camera_panel.disable_controls_initially()  # This handles inner controls too
            # Start/Stop buttons on camera_panel are also handled by disable_controls_initially

    def _run_camera_setup(self):
        log.info("Camera Setup menu action triggered.")
        if not is_ic4_fully_initialized():
            QMessageBox.warning(
                self,
                "IC4 SDK Not Ready",
                "The IC4 SDK is not fully configured (CTI file might be missing or invalid). Please configure it first via 'Camera > Change CTI File...'.",
            )
            return

        # If a camera is running, ask to stop it first or handle re-init carefully
        if self.camera_thread and self.camera_thread.isRunning():
            reply = QMessageBox.question(
                self,
                "Camera Active",
                "A camera stream is active. It needs to be stopped to re-scan or select a new camera. Stop current stream?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                self._on_stop_live_button_pressed()
                # Give a moment for the thread to stop. A more robust way is to wait for finished signal.
                QTimer.singleShot(200, self._proceed_with_camera_setup_dialog)
            else:
                return  # User cancelled
        else:
            self._proceed_with_camera_setup_dialog()

    def _proceed_with_camera_setup_dialog(self):
        """Actual logic to show a camera selection dialog if multiple cameras exist."""
        try:
            devices = ic4.DeviceEnum.devices()
        except Exception as e:
            QMessageBox.critical(
                self, "Device Enumeration Error", f"Could not list cameras: {e}"
            )
            return

        if not devices:
            QMessageBox.information(self, "No Cameras", "No IC4 cameras found.")
            if self.camera_panel:
                self.camera_panel.setEnabled(True)
                self.camera_panel.start_btn.setEnabled(True)
            return

        if len(devices) == 1:
            log.info("Only one camera found. Attempting to initialize it.")
            # Reuse _initialize_camera_on_startup logic which picks the first (only) device
            self._initialize_camera_on_startup()
            return

        # Multiple devices found, show a selection dialog
        items = [f"{dev.model_name} (SN: {dev.serial or 'N/A'})" for dev in devices]
        item, ok = QInputDialog.getItem(
            self, "Select Camera", "Available cameras:", items, 0, False
        )

        if ok and item:
            selected_index = items.index(item)
            selected_device_info = devices[selected_index]

            cam_model = getattr(selected_device_info, "model_name", "Unknown")
            cam_serial = getattr(selected_device_info, "serial", "N/A")
            cam_unique = getattr(selected_device_info, "unique_name", "")

            identifier_to_use = (
                cam_serial
                if cam_serial and cam_serial != "N/A"
                else cam_unique if cam_unique else cam_model
            )

            log.info(
                f"User selected camera: {cam_model} (ID to use: {identifier_to_use})"
            )
            self.camera_settings["cameraModel"] = cam_model
            self.camera_settings["cameraSerial"] = cam_serial
            self.camera_settings["cameraIdentifier"] = identifier_to_use

            self._start_sdk_camera_thread(identifier_to_use, DEFAULT_FPS)
            save_app_setting(SETTING_LAST_CAMERA_SERIAL, identifier_to_use)
        else:
            log.info("Camera selection cancelled by user.")

    def _init_paths_and_icons(self):
        base = os.path.dirname(os.path.abspath(__file__))
        icon_dir = os.path.join(base, "ui", "icons")
        if not os.path.isdir(icon_dir):
            alt_icon_dir = os.path.join(
                os.path.dirname(base), "prim_app", "ui", "icons"
            )
            if os.path.isdir(alt_icon_dir):
                icon_dir = alt_icon_dir
            else:
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
        self.setCentralWidget(central)
        main_v_layout = QVBoxLayout(central)
        main_v_layout.setContentsMargins(2, 2, 2, 2)
        main_v_layout.setSpacing(3)

        self.top_row_widget = QWidget()
        top_h_layout = QHBoxLayout(self.top_row_widget)
        top_h_layout.setContentsMargins(0, 0, 0, 0)
        top_h_layout.setSpacing(4)

        self.camera_panel = CameraControlPanel(self)
        self.top_ctrl = TopControlPanel(self)

        top_h_layout.addWidget(self.camera_panel, 1)
        top_h_layout.addWidget(self.top_ctrl, 2)
        self.top_row_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        main_v_layout.addWidget(self.top_row_widget, 0)

        self.bottom_split = QSplitter(Qt.Horizontal)
        self.bottom_split.setChildrenCollapsible(False)
        self.camera_view = GLViewfinder(self)
        self.pressure_plot_widget = PressurePlotWidget(self)
        self.bottom_split.addWidget(self.camera_view)
        self.bottom_split.addWidget(self.pressure_plot_widget)
        self.bottom_split.setStretchFactor(0, 2)
        self.bottom_split.setStretchFactor(1, 1)
        main_v_layout.addWidget(self.bottom_split, 1)

    def _build_menus(self):
        mb = self.menuBar()
        fm = mb.addMenu("&File")
        exp_data_act = QAction(
            "Export Plot &Data (CSV)…", self, triggered=self._export_plot_data_as_csv
        )
        fm.addAction(exp_data_act)
        exp_img_act = QAction("Export Plot &Image…", self)
        if (
            hasattr(self, "pressure_plot_widget") and self.pressure_plot_widget
        ):  # Should exist by now
            exp_img_act.triggered.connect(self.pressure_plot_widget.export_as_image)
        fm.addAction(exp_img_act)
        fm.addSeparator()
        fm.addAction(
            QAction("&Exit", self, shortcut=QKeySequence.Quit, triggered=self.close)
        )

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
        if hasattr(self, "dock_console") and self.dock_console:  # Should exist
            vm.addAction(self.dock_console.toggleViewAction())

        pm = mb.addMenu("&Plot")
        pm.addAction(
            QAction("&Clear Plot Data", self, triggered=self._clear_pressure_plot)
        )

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

        pm.addAction(QAction("&Reset Plot Zoom", self, triggered=trigger_reset_zoom))

        hm = mb.addMenu("&Help")
        hm.addAction(
            QAction(f"&About {APP_NAME}", self, triggered=self._show_about_dialog)
        )
        hm.addAction(QAction("About &Qt", QApplication.instance().aboutQt))

        cam_menu = mb.addMenu("&Camera")
        cam_menu.addAction(
            QAction(
                "Select/Re-initialize Camera…", self, triggered=self._run_camera_setup
            )
        )
        cam_menu.addAction(
            QAction("Change CTI File...", self, triggered=self._change_cti_file)
        )

    def _change_cti_file(self):
        current_cti_path = load_app_setting(SETTING_CTI_PATH, "")
        cti_dir = os.path.dirname(current_cti_path) if current_cti_path else ""
        cti_path, _ = QFileDialog.getOpenFileName(
            self, "Select GenTL Producer File (.cti)", cti_dir, "*.cti"
        )
        if not cti_path or not os.path.exists(cti_path):
            log.info("No CTI file selected or file does not exist.")
            return

        if self.camera_thread and self.camera_thread.isRunning():
            log.info("Stopping existing camera thread before changing CTI file.")
            self._on_stop_live_button_pressed()
            # Need to wait for thread to fully stop. This is tricky without blocking UI.
            # A QTimer or waiting for the 'finished' signal is better.
            # For now, assume quick stop or user retries if CTI change fails due to active thread.
            QApplication.processEvents()  # Give a moment

        try:
            if prim_app.IC4_LIBRARY_INITIALIZED:
                log.info("Exiting IC4 library before re-initializing with new CTI...")
                ic4.Library.exit()
                prim_app.IC4_LIBRARY_INITIALIZED = False
                prim_app.IC4_GENTL_SYSTEM_CONFIGURED = False

            initialize_ic4_with_cti(cti_path)
            QMessageBox.information(
                self,
                "CTI Changed",
                f"Successfully loaded new CTI: {os.path.basename(cti_path)}\nAttempting to re-initialize camera if possible.",
            )
            self.statusBar().showMessage(
                f"CTI changed to: {os.path.basename(cti_path)}. Re-initializing camera...",
                7000,
            )

            if is_ic4_fully_initialized():
                QTimer.singleShot(0, self._initialize_camera_on_startup)
            else:
                if self.camera_panel:
                    self.camera_panel.setEnabled(False)
                    self.camera_panel.disable_controls_initially()
        except Exception as exc:
            log.exception(
                f"Failed to change and initialize with new CTI file '{cti_path}': {exc}"
            )
            QMessageBox.critical(
                self,
                "CTI Change Error",
                f"Could not load or initialize with new CTI: {exc}",
            )
            if self.camera_panel:
                self.camera_panel.setEnabled(False)
                self.camera_panel.disable_controls_initially()

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
            for p_dev, p_desc in ports:
                self.serial_port_combobox.addItem(
                    f"{os.path.basename(p_dev)} ({p_desc})", QVariant(p_dev)
                )
        else:
            self.serial_port_combobox.addItem("No Serial Ports Found", QVariant())
            self.serial_port_combobox.setEnabled(False)
        tb.addWidget(self.serial_port_combobox)
        tb.addSeparator()
        if hasattr(self, "start_recording_action"):
            tb.addAction(self.start_recording_action)  # Should exist
        if hasattr(self, "stop_recording_action"):
            tb.addAction(self.stop_recording_action)  # Should exist

    def _build_status_bar(self):
        sb = self.statusBar()
        self.app_session_time_label = QLabel("Session: 00:00:00")
        sb.addPermanentWidget(self.app_session_time_label)
        self._app_session_seconds = 0
        self._app_session_timer = QTimer(self)
        self._app_session_timer.setInterval(1000)
        self._app_session_timer.timeout.connect(self._update_app_session_time)
        self._app_session_timer.start()

    # --- Camera Start/Stop Button Handlers (from CameraControlPanel) ---
    def _on_start_live_button_pressed(self):
        log.info("Start Live button pressed.")
        if not is_ic4_fully_initialized():
            QMessageBox.warning(
                self,
                "IC4 Not Ready",
                "IC4 SDK is not fully initialized. Configure CTI via Camera Menu.",
            )
            return
        if self.camera_thread and self.camera_thread.isRunning():
            log.info("Camera is already running.")
            return

        cam_id_to_use = self.camera_settings.get("cameraIdentifier")
        if not cam_id_to_use:
            log.info(
                "No camera identifier known, running camera setup/detection first."
            )
            self._run_camera_setup()  # This will attempt to find/select and then start
        else:
            log.info(f"Attempting to start known camera: {cam_id_to_use}")
            self._start_sdk_camera_thread(cam_id_to_use, DEFAULT_FPS)

    def _on_stop_live_button_pressed(self):
        log.info("Stop Live button pressed.")
        if self.camera_thread and self.camera_thread.isRunning():
            self.camera_thread.stop()
            # The SDKCameraThread.stop() is blocking and handles its own cleanup messages.
            # The _handle_camera_thread_finished slot will update UI once thread truly stops.
        else:
            log.info("Camera thread not running or does not exist to stop.")
            # Ensure UI consistency if stop is pressed when not running
            if self.camera_panel:
                self.camera_panel.start_btn.setEnabled(True)
                self.camera_panel.stop_btn.setEnabled(False)
                if hasattr(self.camera_panel, "enable_adjustment_controls"):
                    self.camera_panel.enable_adjustment_controls(False)
            self.statusBar().showMessage(
                "Camera already stopped or not initialized.", 3000
            )

    # --- Serial Port related methods ---
    @pyqtSlot(str)
    def _handle_serial_status_change(self, status: str):
        log.info(f"Serial status: {status}")
        self.statusBar().showMessage(f"PRIM Device: {status}", 4000)
        connected = (
            "connected" in status.lower()
            or "opened serial port" in status.lower()
            or "simulation mode" in status.lower()
        )
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
            self.pressure_plot_widget.clear_plot()
            sim_mode = "simulation mode" in status.lower()
            self.pressure_plot_widget._update_placeholder(
                f"Waiting for PRIM device data{' (Simulation)' if sim_mode else ''}..."
            )
        if not connected and self._is_recording:
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
        if (
            "disconnecting" in msg.lower()
            or "error opening" in msg.lower()
            or "serial error" in msg.lower()
        ):
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
            if not (
                "error" in current_conn_text
                or "failed" in current_conn_text
                or "disconnected" in current_conn_text
            ):
                if "simulation" not in current_conn_text:
                    self._handle_serial_status_change("Disconnected")
            # self._serial_thread.deleteLater() # Already parented, Qt should handle it, or let it be overwritten.
            self._serial_thread = None
            log.info("Current _serial_thread instance reference cleared.")
        elif sender and isinstance(sender, SerialThread):
            log.warning(
                "Received 'finished' from an orphaned SerialThread. Letting Qt manage it."
            )
            # sender.deleteLater()
        else:
            log.warning(
                "Received 'finished' signal, but sender is not expected SerialThread or is None."
            )
        self._update_recording_actions_enable_state()

    @pyqtSlot(int, float, float)
    def _handle_new_serial_data(self, idx: int, t: float, p: float):
        plot_ctrls = getattr(self.top_ctrl, "plot_controls", None)
        if plot_ctrls:
            self.top_ctrl.update_prim_data(idx, t, p)
            if self.pressure_plot_widget:
                self.pressure_plot_widget.update_plot(
                    t,
                    p,
                    plot_ctrls.auto_x_cb.isChecked(),
                    plot_ctrls.auto_y_cb.isChecked(),
                )
        if self._is_recording and self._recording_worker:
            try:
                self._recording_worker.add_csv_data(t, idx, p)
            except Exception as e_csv:
                log.exception(f"Error adding CSV data to recording queue: {e_csv}")
                self.statusBar().showMessage("CRITICAL: Error queueing CSV data.", 5000)

    def _toggle_serial_connection(self):
        if self._serial_thread and self._serial_thread.isRunning():
            log.info("User requested to stop serial connection.")
            self._serial_thread.stop()
        else:
            idx = self.serial_port_combobox.currentIndex()
            port_var = self.serial_port_combobox.itemData(idx)
            port = port_var if isinstance(port_var, str) else None
            is_sim = "simulated data" in self.serial_port_combobox.currentText().lower()
            if not port and not is_sim:
                QMessageBox.warning(
                    self, "Serial Error", "Select valid port or 'Simulated Data'."
                )
                return
            log.info(
                f"User requested to start serial: Port='{port if port else 'Simulation'}'"
            )
            if self._serial_thread:
                if self._serial_thread.isRunning():
                    self._serial_thread.stop()
                    self._serial_thread.wait(500)
                # self._serial_thread.deleteLater(); # Let new assignment or Qt manage old if parented
                self._serial_thread = None
                QApplication.processEvents()
            try:
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
                log.exception("Failed to create or start SerialThread.")
                QMessageBox.critical(self, "Serial Error", f"Could not start: {e}")
                if self._serial_thread:
                    self._serial_thread = None  # Clear ref
                self._update_recording_actions_enable_state()

    # --- Recording related methods ---
    def _update_recording_actions_enable_state(self):
        serial_ready = (
            self._serial_thread
            and self._serial_thread.isRunning()
            and (
                "connected" in self.top_ctrl.conn_lbl.text().lower()
                or "simulation mode" in self.top_ctrl.conn_lbl.text().lower()
                or "opened serial port" in self.top_ctrl.conn_lbl.text().lower()
            )
        )
        can_start = serial_ready and not self._is_recording
        can_stop = self._is_recording
        if hasattr(self, "start_recording_action"):
            self.start_recording_action.setEnabled(can_start)
        if hasattr(self, "stop_recording_action"):
            self.stop_recording_action.setEnabled(can_stop)

    def _trigger_start_recording_dialog(self):
        serial_active = (
            self._serial_thread
            and self._serial_thread.isRunning()
            and (
                "connected" in self.top_ctrl.conn_lbl.text().lower()
                or "simulation mode" in self.top_ctrl.conn_lbl.text().lower()
                or "opened serial port" in self.top_ctrl.conn_lbl.text().lower()
            )
        )
        if not serial_active:
            QMessageBox.warning(
                self, "Cannot Record", "PRIM device/simulation not active."
            )
            return
        if self._is_recording:
            QMessageBox.information(
                self, "Recording Active", "Recording already in progress."
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("New Recording Session")
        layout = QFormLayout(dialog)
        def_session_name = (
            f"Session_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}"
        )
        name_edit = QLineEdit(def_session_name)
        layout.addRow("Session Name:", name_edit)
        op_edit = QLineEdit(load_app_setting("last_operator", ""))
        layout.addRow("Operator:", op_edit)
        notes_edit = QTextEdit()
        notes_edit.setFixedHeight(80)
        layout.addRow("Notes:", notes_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec_() != QDialog.Accepted:
            log.info("Recording dialog cancelled.")
            return
        save_app_setting("last_operator", op_edit.text())
        session_name_raw = name_edit.text().strip() or def_session_name
        session_name_safe = "".join(
            c if c.isalnum() or c in ("_", "-") else "_" for c in session_name_raw
        )
        session_name_safe = (
            re.sub(r"_+", "_", session_name_safe).strip("_")
            or f"Session_Unnamed_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}"
        )

        session_folder = os.path.join(PRIM_RESULTS_DIR, session_name_safe)
        try:
            os.makedirs(session_folder, exist_ok=True)
        except OSError as e_mkdir:
            log.error(f"Failed to create session folder '{session_folder}': {e_mkdir}")
            QMessageBox.critical(
                self, "File Error", f"Could not create folder:\n{e_mkdir}"
            )
            return

        self.last_trial_basepath = session_folder
        recording_base_prefix = os.path.join(session_folder, session_name_safe)

        w, h = DEFAULT_FRAME_SIZE
        record_fps = DEFAULT_FPS

        current_cam_w, current_cam_h, current_cam_fps = 0, 0, 0
        if self.camera_thread and self.camera_thread.isRunning():
            # Attempt to get current actuals from camera_info_updated's last payload
            # This assumes camera_info_updated has been emitted and info is stored in camera_settings
            # or directly queryable. For now, we'll use a simplified placeholder from camera_settings if available.
            info = self.camera_settings.get(
                "_last_cam_info_dict", {}
            )  # Hypothetical storage
            if (
                not info and self.camera_panel
            ):  # Fallback to reading from status label (less ideal)
                try:
                    res_parts = self.camera_panel.cam_current_res_label.text().split(
                        "x"
                    )
                    fps_part = self.camera_panel.cam_current_fps_label.text()
                    if len(res_parts) == 2:
                        current_cam_w, current_cam_h = int(res_parts[0]), int(
                            res_parts[1]
                        )
                    current_cam_fps = float(fps_part)
                except:
                    pass  # Ignore parsing errors

            if current_cam_w > 0 and current_cam_h > 0:
                w, h = current_cam_w, current_cam_h
            if current_cam_fps > 0:
                record_fps = current_cam_fps
            log.info(
                f"Using live camera params for recording: {w}x{h} @ {record_fps:.1f} FPS"
            )
        else:
            log.warning(
                "Camera not active or params unavailable, using default frame size/FPS for recording."
            )

        video_ext = DEFAULT_VIDEO_EXTENSION.lower()
        codec = DEFAULT_VIDEO_CODEC
        log.info(
            f"Recording: Session='{session_name_safe}'. Target: FPS={record_fps}, Size={w}x{h}, Format={video_ext}/{codec}"
        )

        try:
            if self._recording_worker and self._recording_worker.isRunning():
                self._recording_worker.stop_worker()
                if not self._recording_worker.wait(2000):
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
                parent=self,
            )
            self._recording_worker.start()
            QThread.msleep(700)

            if not (
                self._recording_worker
                and self._recording_worker.isRunning()
                and self._recording_worker.is_ready_to_record
            ):
                raise RuntimeError(
                    "Recording worker/TrialRecorder failed readiness. Check logs."
                )

            self._is_recording = True
            if hasattr(self, "start_recording_action"):
                self.start_recording_action.setIcon(self.icon_recording_active)
            self._update_recording_actions_enable_state()
            if self.pressure_plot_widget:
                self.pressure_plot_widget.clear_plot()
            self.statusBar().showMessage(f"🔴 REC: {session_name_safe}", 0)
            log.info(f"Recording started: {session_name_safe}")

        except Exception as e_rec_start:
            log.exception(f"Critical error starting recording: {e_rec_start}")
            QMessageBox.critical(
                self, "Recording Error", f"Could not start recording: {e_rec_start}"
            )
            if self._recording_worker:
                if self._recording_worker.isRunning():
                    self._recording_worker.stop_worker()
                    self._recording_worker.wait(500)
                self._recording_worker.deleteLater()
                self._recording_worker = None
            self._is_recording = False
            self._update_recording_actions_enable_state()
            if self.statusBar().currentMessage().startswith("🔴 REC:"):
                self.statusBar().clearMessage()
            return

    def _trigger_stop_recording(self):
        if not self._is_recording or not self._recording_worker:
            log.info("Stop recording: not recording or worker missing.")
            if self._is_recording:
                self._is_recording = False
            self._update_recording_actions_enable_state()
            if self.statusBar().currentMessage().startswith("🔴 REC:"):
                self.statusBar().clearMessage()
            return
        log.info("User requested stop recording...")
        session_name_stopped = (
            os.path.basename(self.last_trial_basepath)
            if hasattr(self, "last_trial_basepath") and self.last_trial_basepath
            else "Session"
        )
        try:
            self._recording_worker.stop_worker()
            if not self._recording_worker.wait(10000):
                self._recording_worker.terminate()
                self._recording_worker.wait(1000)
            log.info("RecordingWorker thread finished/terminated.")
            count = (
                self._recording_worker.video_frame_count
                if hasattr(self._recording_worker, "video_frame_count")
                else 0
            )
            self.statusBar().showMessage(
                f"Recording '{session_name_stopped}' stopped. {count} frames.", 7000
            )
            if hasattr(self, "last_trial_basepath") and self.last_trial_basepath:
                self._save_current_plot_data_for_session()
                if (
                    QMessageBox.information(
                        self,
                        "Recording Saved",
                        f"Session '{session_name_stopped}' saved to:\n{self.last_trial_basepath}\nFrames: {count}\n\nOpen folder?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No,
                    )
                    == QMessageBox.Yes
                ):
                    try:
                        if sys.platform == "win32":
                            os.startfile(self.last_trial_basepath)
                        elif sys.platform == "darwin":
                            os.system(f'open "{self.last_trial_basepath}"')
                        else:
                            os.system(f'xdg-open "{self.last_trial_basepath}"')
                    except Exception as e_open:
                        log.error(f"Error opening folder: {e_open}")
                        QMessageBox.warning(
                            self, "Open Error", f"Could not open folder:\n{e_open}"
                        )
            else:
                QMessageBox.information(
                    self,
                    "Recording Stopped",
                    f"{count} frames recorded. Path info missing.",
                )
        except Exception as e_stop_rec:
            log.exception(f"Error stopping recording: {e_stop_rec}")
            self.statusBar().showMessage(f"Error stopping: {e_stop_rec}", 5000)
        finally:
            if self._recording_worker:
                self._recording_worker.deleteLater()
            self._recording_worker = None
            self._is_recording = False
            if hasattr(self, "start_recording_action"):
                self.start_recording_action.setIcon(self.icon_record_start)
            self._update_recording_actions_enable_state()
            if self.statusBar().currentMessage().startswith("🔴 REC:"):
                self.statusBar().clearMessage()
            log.info("Recording fully stopped and UI updated.")

    def _save_current_plot_data_for_session(self):
        if not (
            hasattr(self, "last_trial_basepath")
            and self.last_trial_basepath
            and self.pressure_plot_widget
            and self.pressure_plot_widget.times
            and self.pressure_plot_widget.pressures
        ):
            log.warning("Cannot auto-save plot: path or data missing.")
            return
        session_name = os.path.basename(self.last_trial_basepath) or "session_plot"
        csv_path = os.path.join(
            self.last_trial_basepath, f"{session_name}_pressure_plot_data.csv"
        )
        try:
            with open(csv_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["time_s", "pressure_mmHg"])
                for t, p in zip(
                    self.pressure_plot_widget.times, self.pressure_plot_widget.pressures
                ):
                    writer.writerow([f"{t:.6f}", f"{p:.6f}"])
            log.info(f"Session plot data saved to: {csv_path}")
            self.statusBar().showMessage(f"Plot CSV for '{session_name}' saved.", 4000)
        except Exception as e_save_plot:
            log.exception(f"Failed to auto-save plot to '{csv_path}': {e_save_plot}")
            QMessageBox.warning(
                self, "Plot Save Error", f"Could not save plot CSV:\n{e_save_plot}"
            )

    @pyqtSlot()
    def _clear_pressure_plot(self):
        if self.pressure_plot_widget:
            self.pressure_plot_widget.clear_plot()
            self.statusBar().showMessage("Pressure plot cleared.", 3000)

    @pyqtSlot()
    def _export_plot_data_as_csv(self):
        if not (
            self.pressure_plot_widget
            and self.pressure_plot_widget.times
            and self.pressure_plot_widget.pressures
        ):
            QMessageBox.information(self, "No Data", "Plot has no data to export.")
            return
        def_fn = f"manual_plot_export_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Plot Data as CSV", def_fn, "CSV Files (*.csv)"
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
            log.info(f"Plot manually exported: {path}")
        except Exception as e_export:
            log.exception(f"Failed to manually export plot to '{path}': {e_export}")
            QMessageBox.critical(
                self, "Export Error", f"Could not save CSV:\n{e_export}"
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

        if self.camera_thread:
            if self.camera_thread.isRunning():
                log.info("Stopping camera thread due to reported error...")
                self.camera_thread.stop()
            # self.camera_thread.deleteLater() # Let finished signal handle deleteLater if connected
            # self.camera_thread = None # Clear ref in finished signal

        # Reset UI related to camera panel
        if self.camera_panel:
            self.camera_panel.setEnabled(True)  # Keep panel enabled, but...
            self.camera_panel.start_btn.setEnabled(
                True
            )  # Allow user to try starting again
            self.camera_panel.stop_btn.setEnabled(False)
            if hasattr(self.camera_panel, "enable_adjustment_controls"):
                self.camera_panel.enable_adjustment_controls(
                    False
                )  # Disable adjustments tab
            self.camera_panel.update_status_info()  # Clear status fields

        self.statusBar().showMessage("Camera Error! Live feed stopped or failed.", 0)

        if self._is_recording:
            log.warning("Camera error during active recording. Stopping recording.")
            self._trigger_stop_recording()

    def closeEvent(self, event):
        log.info("MainWindow closeEvent triggered.")
        if self._is_recording:
            reply = QMessageBox.question(
                self,
                "Confirm Exit",
                "Recording active. Stop and exit?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self._trigger_stop_recording()
            else:
                event.ignore()
                return

        # Gracefully stop camera thread first if it's running
        if self.camera_thread and self.camera_thread.isRunning():
            log.info("Stopping CameraThread on application close...")
            self.camera_thread.stop()  # This method in SDKCameraThread includes a wait()
            # self.camera_thread.deleteLater() # Let its finished signal handle deletion.
            self.camera_thread = (
                None  # Clear reference, finished signal will try to deleteLater.
            )

        # Gracefully stop serial thread
        if self._serial_thread and self._serial_thread.isRunning():
            log.info("Stopping SerialThread on application close...")
            self._serial_thread.stop()
            # self._serial_thread.deleteLater()
            self._serial_thread = None

        # Recording worker should already be stopped if was active
        if self._recording_worker and self._recording_worker.isRunning():
            log.warning(
                "RecordingWorker still running during closeEvent despite earlier checks. Forcing stop."
            )
            self._recording_worker.stop_worker()
            if not self._recording_worker.wait(3000):
                self._recording_worker.terminate()
                self._recording_worker.wait(500)
            # self._recording_worker.deleteLater()
            self._recording_worker = None

        # Allow Qt event loop to process deleteLater calls for threads
        QApplication.processEvents()
        log.info(
            "All threads processed for cleanup. Proceeding with application close."
        )
        super().closeEvent(event)
