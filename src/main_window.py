import os
import csv
import logging

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
)
from PyQt5.QtGui import QIcon, QKeySequence

from threads.qtcamera_widget import QtCameraWidget
from threads.serial_thread import SerialThread
from recording import TrialRecorder
from utils import list_serial_ports

from control_panels.camera_control_panel import CameraControlPanel
from control_panels.plot_control_panel import PlotControlPanel
from control_panels.top_control_panel import TopControlPanel

from canvas.pressure_plot_widget import PressurePlotWidget

from config import (
    APP_NAME,
    APP_VERSION,
    ABOUT_TEXT,
    LOG_LEVEL,
    DEFAULT_FPS,
    DEFAULT_FRAME_SIZE,
    DEFAULT_CAMERA_INDEX,
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

        self._init_paths_and_icons()
        self._build_console()
        self._build_central()
        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()

        self.showMaximized()
        QTimer.singleShot(300, self._adjust_splitter)
        self.statusBar().showMessage("Ready. Select camera and serial port.", 5000)

        self._initial_control_state()
        self._connect_top_controls()
        self._connect_camera_widget()
        QTimer.singleShot(100, self.top_ctrl.camera_controls.populate_cameras)

    def _init_paths_and_icons(self):
        base = os.path.dirname(__file__)
        icon_dir = os.path.join(base, "icons")
        self.icon_record_start = QIcon(os.path.join(icon_dir, "record.svg"))
        self.icon_record_stop = QIcon(os.path.join(icon_dir, "stop.svg"))
        self.icon_recording_active = QIcon(
            os.path.join(icon_dir, "recording_active.svg")
        )
        self.icon_connect = QIcon(os.path.join(icon_dir, "plug.svg"))
        self.icon_disconnect = QIcon(os.path.join(icon_dir, "plug-disconnect.svg"))

    def _build_console(self):
        self.dock_console = QDockWidget("Console Log", self)
        self.dock_console.setAllowedAreas(
            Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea
        )
        console = QWidget()
        lay = QVBoxLayout(console)
        self.console_out = QTextEdit(readOnly=True)
        lay.addWidget(self.console_out)
        self.dock_console.setWidget(console)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.dock_console)
        self.dock_console.setVisible(False)

    def _build_central(self):
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(2, 2, 2, 2)
        outer.setSpacing(3)

        self.top_ctrl = TopControlPanel(self)
        self.top_ctrl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        outer.addWidget(self.top_ctrl)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)

        self.qt_cam = QtCameraWidget(self)
        self.plot_w = PressurePlotWidget(self)

        self.main_splitter.addWidget(self.qt_cam)
        self.main_splitter.addWidget(self.plot_w)
        self.main_splitter.setStretchFactor(0, 2)
        self.main_splitter.setStretchFactor(1, 3)

        outer.addWidget(self.main_splitter, 1)
        self.setCentralWidget(central)

    def _build_menu(self):
        mb = self.menuBar()
        file_m = mb.addMenu("&File")
        exp_csv = QAction("Export Plot &Data…", self)
        exp_csv.triggered.connect(self._export_plot_csv)
        file_m.addAction(exp_csv)
        exp_img = QAction("Export Plot &Image…", self)
        exp_img.triggered.connect(self.plot_w.export_as_image)
        file_m.addAction(exp_img)
        file_m.addSeparator()
        exit_a = QAction("&Exit", self, shortcut=QKeySequence.Quit)
        exit_a.triggered.connect(self.close)
        file_m.addAction(exit_a)

        acq_m = mb.addMenu("&Acquisition")
        self.start_action = QAction(
            self.icon_record_start,
            "Start Recording",
            self,
            shortcut=Qt.CTRL | Qt.Key_R,
            triggered=self._start_pc_recording,
            enabled=False,
        )
        acq_m.addAction(self.start_action)
        self.stop_action = QAction(
            self.icon_record_stop,
            "Stop Recording",
            self,
            shortcut=Qt.CTRL | Qt.Key_T,
            triggered=self._stop_pc_recording,
            enabled=False,
        )
        acq_m.addAction(self.stop_action)

        view_m = mb.addMenu("&View")
        view_m.addAction(self.dock_console.toggleViewAction())

        plot_m = mb.addMenu("&Plot")
        clear_a = QAction("Clear Plot Data", self, triggered=self._on_clear_plot)
        plot_m.addAction(clear_a)
        reset_a = QAction(
            "Reset Zoom",
            self,
            triggered=lambda: self.plot_w.reset_zoom(
                self.top_ctrl.plot_controls.auto_x_cb.isChecked(),
                self.top_ctrl.plot_controls.auto_y_cb.isChecked(),
            ),
        )
        plot_m.addAction(reset_a)

        help_m = mb.addMenu("&Help")
        about_a = QAction("&About", self, triggered=self._on_about)
        help_m.addAction(about_a)
        help_m.addAction("About &Qt", QApplication.instance().aboutQt)

    def _build_toolbar(self):
        tb = QToolBar("Main Controls")
        tb.setIconSize(QSize(20, 20))
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(Qt.TopToolBarArea, tb)

        self.act_connect = QAction(
            self.icon_connect, "&Connect PRIM", self, triggered=self._toggle_serial
        )
        tb.addAction(self.act_connect)

        self.port_combo = QComboBox()
        self.port_combo.addItem("🔌 Simulated Data", None)
        for port, desc in list_serial_ports() or []:
            self.port_combo.addItem(f"{port} ({desc})", port)
        tb.addWidget(self.port_combo)

        self.format_combo = QComboBox()
        for fmt in SUPPORTED_FORMATS:
            self.format_combo.addItem(fmt.upper(), fmt)
        self.format_combo.setCurrentText(DEFAULT_VIDEO_EXTENSION.upper())
        tb.addWidget(self.format_combo)

        tb.addSeparator()
        tb.addAction(self.start_action)
        tb.addAction(self.stop_action)

    def _build_statusbar(self):
        sb = self.statusBar() or QStatusBar(self)
        self.setStatusBar(sb)
        self.app_time_lbl = QLabel("Session: 00:00:00")
        sb.addPermanentWidget(self.app_time_lbl)
        self._app_secs = 0
        timer = QTimer(self, interval=1000, timeout=self._tick_app_time)
        timer.start()

    def _initial_control_state(self):
        self.top_ctrl.update_connection_status("Disconnected", False)
        self.top_ctrl.disable_all_camera_controls()

    def _connect_top_controls(self):
        tc = self.top_ctrl
        tc.camera_selected.connect(self._on_camera_device_selected)
        tc.resolution_selected.connect(self._on_resolution_selected)
        tc.exposure_changed.connect(lambda v: self.qt_cam.set_exposure(v))
        tc.gain_changed.connect(lambda v: self.qt_cam.set_gain(v))
        tc.brightness_changed.connect(lambda v: self.qt_cam.set_brightness(v))
        tc.auto_exposure_toggled.connect(lambda c: self.qt_cam.set_auto_exposure(c))
        tc.roi_changed.connect(
            lambda x, y, w, h: self.qt_cam.set_software_roi(x, y, w, h)
        )
        tc.roi_reset_requested.connect(self.qt_cam.reset_roi_to_default)
        pc = tc.plot_controls
        pc.x_axis_limits_changed.connect(self.plot_w.set_manual_x_limits)
        pc.y_axis_limits_changed.connect(self.plot_w.set_manual_y_limits)
        pc.export_plot_image_requested.connect(self.plot_w.export_as_image)
        pc.reset_btn.clicked.connect(
            lambda: self.plot_w.reset_zoom(
                pc.auto_x_cb.isChecked(), pc.auto_y_cb.isChecked()
            )
        )

    def _connect_camera_widget(self):
        self.qt_cam.camera_resolutions_updated.connect(
            self.top_ctrl.update_camera_resolutions
        )
        self.qt_cam.camera_error.connect(self._on_camera_error)
        self.qt_cam.camera_properties_updated.connect(
            self.top_ctrl.update_camera_ui_from_properties
        )

    def _adjust_splitter(self):
        # relies on stretch factors set in _build_central
        pass

    @pyqtSlot(int, str)
    def _on_camera_device_selected(self, cam_id, desc):
        if cam_id < 0:
            self.qt_cam.set_active_camera(-1, "")
            self.top_ctrl.disable_all_camera_controls()
            self.top_ctrl.update_camera_resolutions([])
        else:
            self.qt_cam.set_active_camera(cam_id, desc)

    @pyqtSlot(str)
    def _on_resolution_selected(self, res_str):
        try:
            w, h = map(int, res_str.split("x"))
            self.qt_cam.set_active_resolution(w, h)
        except ValueError:
            log.warning("Invalid resolution: %s", res_str)

    @pyqtSlot(str, str)
    def _on_camera_error(self, msg, code):
        log.error("Camera Error: %s (%s)", msg, code)
        self.statusBar().showMessage(f"Camera Error: {msg}", 5000)
        self.top_ctrl.disable_all_camera_controls()
        self.start_action.setEnabled(False)

    def _toggle_serial(self):
        if not (self._serial_thread and self._serial_thread.isRunning()):
            port = self.port_combo.currentData()
            if port in ("NO_PORTS_FOUND_PLACEHOLDER", "ERROR_PORTS_PLACEHOLDER"):
                QMessageBox.warning(self, "Serial", "No valid serial port.")
                return
            try:
                self._serial_thread = SerialThread(port, parent=self)
                self._serial_thread.data_ready.connect(self._on_serial_data)
                self._serial_thread.error_occurred.connect(self._on_serial_error)
                self._serial_thread.status_changed.connect(self._on_serial_status)
                self._serial_thread.finished.connect(self._on_serial_finished)
                self._serial_thread.start()
            except Exception as e:
                log.exception("Failed to start SerialThread")
                QMessageBox.critical(self, "Serial Error", str(e))
                self._serial_thread = None
        else:
            self._serial_thread.stop()

    @pyqtSlot(str)
    def _on_serial_status(self, status):
        self.statusBar().showMessage(f"PRIM: {status}", 4000)
        ok = "connected" in status.lower()
        self.top_ctrl.update_connection_status(status, ok)
        if ok:
            self.act_connect.setIcon(self.icon_disconnect)
            self.act_connect.setText("Disconnect PRIM")
            self.start_action.setEnabled(True)
            self.port_combo.setEnabled(False)
            self.plot_w.clear_plot()
        else:
            self.act_connect.setIcon(self.icon_connect)
            self.act_connect.setText("Connect PRIM")
            if self._is_recording:
                self._stop_pc_recording()
                QMessageBox.warning(self, "Recording Stopped", "PRIM disconnected.")
            self.start_action.setEnabled(False)
            self.port_combo.setEnabled(True)
            self.plot_w._show_placeholder("PRIM disconnected.")

    @pyqtSlot(str)
    def _on_serial_error(self, msg):
        log.error("Serial Error: %s", msg)
        self.statusBar().showMessage(f"PRIM Error: {msg}", 5000)
        self._on_serial_status("Error")

    @pyqtSlot()
    def _on_serial_finished(self):
        self._serial_thread = None
        self._on_serial_status("Disconnected")

    @pyqtSlot(int, float, float)
    def _on_serial_data(self, idx, t_dev, p_dev):
        self.top_ctrl.update_prim_data(idx, t_dev, p_dev)
        auto_x = self.top_ctrl.plot_controls.auto_x_cb.isChecked()
        auto_y = self.top_ctrl.plot_controls.auto_y_cb.isChecked()
        self.plot_w.update_plot(t_dev, p_dev, auto_x, auto_y)
        if self.dock_console.isVisible():
            self.console_out.append(
                f"Data: Idx={idx}, Time={t_dev:.3f}s, P={p_dev:.2f}"
            )
        if self._is_recording:
            try:
                self.trial_recorder.write_csv_data(t_dev, idx, p_dev)
            except Exception:
                log.exception("CSV write failed")
                self._stop_pc_recording()
                self.statusBar().showMessage("CSV write error.", 5000)

    def _start_pc_recording(self):
        if not (self._serial_thread and self._serial_thread.isRunning()):
            QMessageBox.warning(self, "Not Connected", "Connect PRIM first.")
            return
        if not (self.qt_cam._camera_thread and self.qt_cam._camera_thread.isRunning()):
            QMessageBox.warning(self, "Camera Not Ready", "Open camera first.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Start Recording")
        form = QFormLayout(dlg)
        name = QLineEdit(f"Session_{QDateTime.currentDateTime():yyyyMMdd_HHmmss}")
        form.addRow("Session Name:", name)
        operator = QLineEdit()
        form.addRow("Operator:", operator)
        notes = QTextEdit()
        notes.setFixedHeight(70)
        form.addRow("Notes:", notes)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec_() != QDialog.Accepted:
            return

        trial_name = name.text().strip() or name.placeholderText()
        folder = os.path.join(PRIM_RESULTS_DIR, trial_name.replace(" ", "_"))
        os.makedirs(folder, exist_ok=True)
        basepath = os.path.join(folder, trial_name)

        (fw, fh) = getattr(self.qt_cam._camera_thread, "frame_size", DEFAULT_FRAME_SIZE)
        chosen_ext = (
            self.format_combo.currentData() or self.format_combo.currentText().lower()
        )
        chosen_codec = DEFAULT_VIDEO_CODEC

        self.trial_recorder = TrialRecorder(
            basepath=basepath,
            fps=DEFAULT_FPS,
            frame_size=(fw, fh),
            video_ext=chosen_ext,
            video_codec=chosen_codec,
        )
        if not self.trial_recorder.is_recording:
            raise RuntimeError("Recorder failed to start")

        try:
            self.qt_cam.frame_ready.disconnect()
        except Exception:
            pass
        self.qt_cam.frame_ready.connect(
            lambda qimg, arr: self.trial_recorder.write_video_frame(arr)
        )

        self.last_trial_basepath = folder
        self.start_action.setIcon(self.icon_recording_active)
        self.start_action.setEnabled(False)
        self.stop_action.setEnabled(True)
        self._is_recording = True
        self.plot_w.clear_plot()
        self.statusBar().showMessage(f"Recording Started: {trial_name}", 0)

    def _stop_pc_recording(self):
        if self.trial_recorder:
            self.trial_recorder.stop()
            count = getattr(self.trial_recorder, "video_frame_count", "N/A")
            self.statusBar().showMessage(f"Recording Stopped. Frames: {count}", 5000)
            log.info("Recording stopped, frames=%s", count)
            self.trial_recorder = None
        self._is_recording = False
        self.start_action.setIcon(self.icon_record_start)
        self.start_action.setEnabled(bool(self._serial_thread))
        self.stop_action.setEnabled(False)

    @pyqtSlot()
    def _on_clear_plot(self):
        self.plot_w.clear_plot()
        self.statusBar().showMessage("Plot cleared.", 3000)

    @pyqtSlot()
    def _export_plot_csv(self):
        if not self.plot_w.times:
            QMessageBox.information(self, "No Data", "Nothing to export.")
            return
        fname, _ = QFileDialog.getSaveFileName(
            self,
            "Export CSV",
            f"plot_{QDateTime.currentDateTime():yyyyMMdd_HHmmss}.csv",
            "CSV Files (*.csv)",
        )
        if not fname:
            return
        with open(fname, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["time_s", "pressure_mmHg"])
            for t, p in zip(self.plot_w.times, self.plot_w.pressures):
                writer.writerow([f"{t:.3f}", f"{p:.2f}"])
        self.statusBar().showMessage(
            f"Plot data exported to {os.path.basename(fname)}", 3000
        )

    @pyqtSlot()
    def _on_about(self):
        QMessageBox.about(self, f"About {APP_NAME}", ABOUT_TEXT)

    def _tick_app_time(self):
        self._app_secs += 1
        h, m, s = (
            self._app_secs // 3600,
            (self._app_secs % 3600) // 60,
            self._app_secs % 60,
        )
        self.app_time_lbl.setText(f"Session: {h:02}:{m:02}:{s:02}")

    def closeEvent(self, ev):
        if self._is_recording:
            resp = QMessageBox.question(
                self,
                "Exit?",
                "Recording in progress. Stop and exit?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if resp != QMessageBox.Yes:
                ev.ignore()
                return
            self._stop_pc_recording()
        if self._serial_thread and self._serial_thread.isRunning():
            self._serial_thread.stop()
            if not self._serial_thread.wait(2000):
                self._serial_thread.terminate()
        self.qt_cam.close()
        log.info("Application exiting")
        super().closeEvent(ev)
