import os
import logging
import csv

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QMessageBox,
    QSplitter, QHBoxLayout, QVBoxLayout, QToolBar, QAction,
    QComboBox, QFileDialog, QDockWidget, QTextEdit,
    QLineEdit, QPushButton, QStatusBar, QDialog,
    QFormLayout, QDialogButtonBox, QSpinBox, QDoubleSpinBox,
    QSizePolicy, QCheckBox, QGroupBox, QSlider, QStyleFactory
)
from PyQt5.QtCore    import Qt, QTimer, QSize, pyqtSignal, QDateTime, QUrl
from PyQt5.QtGui     import (
    QIcon, QImage, QPixmap, QPalette, QColor,
    QTextCursor, QKeySequence, QDesktopServices
)
from PyQt5.QtMultimedia import QCameraInfo

from threads.qtcamera_widget import QtCameraWidget
from threads.serial_thread     import SerialThread
from recording                import TrialRecorder
from utils                    import list_serial_ports

from config import (
    DEFAULT_VIDEO_CODEC, DEFAULT_VIDEO_EXTENSION, DEFAULT_FPS, DEFAULT_FRAME_SIZE,
    DEFAULT_CAMERA_INDEX, APP_NAME, APP_VERSION, ABOUT_TEXT, LOG_LEVEL,
    PLOT_MAX_POINTS, PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# Module logger (root configured in prim_app.py)
numeric_log_level_main = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(
    level=numeric_log_level_main,
    format='%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] %(threadName)s - %(message)s'
)
log = logging.getLogger(__name__)


class CameraControlPanel(QGroupBox):
    camera_selected = pyqtSignal(int)
    resolution_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__("Camera", parent)
        layout = QFormLayout(self)
        layout.setSpacing(8)

        self.cam_selector = QComboBox()
        self.cam_selector.setToolTip("Select available camera")
        self.cam_selector.currentIndexChanged.connect(self._on_camera_selected_changed)
        layout.addRow("Device:", self.cam_selector)

        self.res_selector = QComboBox()
        self.res_selector.setToolTip("Select camera resolution")
        self.res_selector.currentIndexChanged.connect(self._on_resolution_selected_changed)
        self.res_selector.setEnabled(False)
        layout.addRow("Resolution:", self.res_selector)

        self.exposure_slider  = QSlider(Qt.Horizontal); self.exposure_slider.setEnabled(False)
        self.gain_slider      = QSlider(Qt.Horizontal); self.gain_slider.setEnabled(False)
        self.brightness_slider= QSlider(Qt.Horizontal); self.brightness_slider.setEnabled(False)
        layout.addRow("Exposure:", self.exposure_slider)
        layout.addRow("Gain:",     self.gain_slider)
        layout.addRow("Brightness:",self.brightness_slider)

        self.populate_camera_selector()

    def populate_camera_selector(self):
        self.cam_selector.clear()
        try:
            cams = QCameraInfo.availableCameras()
            if cams:
                for i, info in enumerate(cams):
                    self.cam_selector.addItem(info.description() or f"Camera {i}", i)
                idx = DEFAULT_CAMERA_INDEX if 0 <= DEFAULT_CAMERA_INDEX < len(cams) else 0
                self.cam_selector.setCurrentIndex(idx)
                cam_id = self.cam_selector.itemData(idx)
                self.camera_selected.emit(cam_id)
            else:
                self.cam_selector.addItem("No Qt cameras found", -1)
                self.cam_selector.setEnabled(False)
        except Exception:
            log.error("Error listing Qt cameras", exc_info=True)
            self.cam_selector.addItem("Error listing cameras", -1)
            self.cam_selector.setEnabled(False)

    def _on_camera_selected_changed(self, index):
        cam_id = self.cam_selector.itemData(index)
        if cam_id is not None and cam_id != -1:
            self.camera_selected.emit(cam_id)
            self.res_selector.clear()
            self.res_selector.setEnabled(False)

    def _on_resolution_selected_changed(self, index):
        res = self.res_selector.itemData(index)
        if res:
            self.resolution_selected.emit(res)

    def update_resolutions(self, res_list):
        cur = self.res_selector.currentData()
        self.res_selector.clear()
        if res_list:
            for r in res_list:
                self.res_selector.addItem(r, r)
            self.res_selector.setEnabled(True)
            if cur and self.res_selector.findData(cur) != -1:
                self.res_selector.setCurrentIndex(self.res_selector.findData(cur))
            else:
                default_str = f"{DEFAULT_FRAME_SIZE[0]}x{DEFAULT_FRAME_SIZE[1]}"
                idx = self.res_selector.findText(default_str)
                if idx != -1:
                    self.res_selector.setCurrentIndex(idx)
        else:
            self.res_selector.addItem("N/A", None)
            self.res_selector.setEnabled(False)

class PlotControlPanel(QGroupBox):
    x_axis_limits_changed = pyqtSignal(float, float)
    y_axis_limits_changed = pyqtSignal(float, float)
    export_plot_image_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Plot", parent)
        layout = QFormLayout(self)
        layout.setSpacing(8)

        self.auto_x_cb = QCheckBox("Auto-scale X"); self.auto_x_cb.setChecked(True)
        layout.addRow(self.auto_x_cb)
        self.x_min = QDoubleSpinBox(); self.x_max = QDoubleSpinBox()
        self.x_min.setEnabled(False); self.x_max.setEnabled(False)
        self.x_min.setDecimals(1); self.x_max.setDecimals(1)
        x_layout = QHBoxLayout()
        x_layout.addWidget(QLabel("Min:")); x_layout.addWidget(self.x_min)
        x_layout.addWidget(QLabel("Max:")); x_layout.addWidget(self.x_max)
        layout.addRow("X-Limits:", x_layout)

        self.auto_y_cb = QCheckBox("Auto-scale Y"); self.auto_y_cb.setChecked(True)
        layout.addRow(self.auto_y_cb)
        self.y_min = QDoubleSpinBox(); self.y_max = QDoubleSpinBox()
        self.y_min.setEnabled(False); self.y_max.setEnabled(False)
        self.y_min.setDecimals(1); self.y_max.setDecimals(1)
        self.y_min.setValue(PLOT_DEFAULT_Y_MIN)
        self.y_max.setValue(PLOT_DEFAULT_Y_MAX)
        y_layout = QHBoxLayout()
        y_layout.addWidget(QLabel("Min:")); y_layout.addWidget(self.y_min)
        y_layout.addWidget(QLabel("Max:")); y_layout.addWidget(self.y_max)
        layout.addRow("Y-Limits:", y_layout)

        self.reset_btn      = QPushButton("↺ Reset Zoom")
        self.export_img_btn = QPushButton("Export Image")
        btns = QHBoxLayout()
        btns.addWidget(self.reset_btn); btns.addWidget(self.export_img_btn)
        layout.addRow(btns)

        self.auto_x_cb.toggled.connect(lambda c: (self.x_min.setEnabled(not c),
                                                  self.x_max.setEnabled(not c)))
        self.auto_y_cb.toggled.connect(lambda c: (self.y_min.setEnabled(not c),
                                                  self.y_max.setEnabled(not c)))
        self.x_min.valueChanged.connect(self._emit_x)
        self.x_max.valueChanged.connect(self._emit_x)
        self.y_min.valueChanged.connect(self._emit_y)
        self.y_max.valueChanged.connect(self._emit_y)
        self.export_img_btn.clicked.connect(self.export_plot_image_requested)

    def _emit_x(self):
        if not self.auto_x_cb.isChecked():
            self.x_axis_limits_changed.emit(self.x_min.value(), self.x_max.value())

    def _emit_y(self):
        if not self.auto_y_cb.isChecked():
            self.y_axis_limits_changed.emit(self.y_min.value(), self.y_max.value())


class TopControlPanel(QWidget):
    camera_selected = pyqtSignal(int)
    resolution_selected = pyqtSignal(str)
    x_axis_limits_changed = pyqtSignal(float, float)
    y_axis_limits_changed = pyqtSignal(float, float)
    export_plot_image_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10,5,10,5)
        layout.setSpacing(15)

        self.camera_controls = CameraControlPanel(self)
        layout.addWidget(self.camera_controls, 1)

        prim_box = QGroupBox("PRIM Device Status")
        prim_form = QFormLayout(prim_box); prim_form.setSpacing(8)
        self.conn_lbl  = QLabel("Disconnected")
        self.conn_lbl.setStyleSheet("font-weight:bold;color:#D6C832;")
        prim_form.addRow("Connection:", self.conn_lbl)
        self.idx_lbl   = QLabel("N/A"); prim_form.addRow("Device Frame #:", self.idx_lbl)
        self.time_lbl  = QLabel("N/A"); prim_form.addRow("Device Time (s):", self.time_lbl)
        self.pres_lbl  = QLabel("N/A")
        self.pres_lbl.setStyleSheet("font-size:14pt;font-weight:bold;")
        prim_form.addRow("Current Pressure:", self.pres_lbl)
        layout.addWidget(prim_box, 1)

        self.plot_controls = PlotControlPanel(self)
        layout.addWidget(self.plot_controls, 1)

        # forward sub‐signals
        self.camera_controls.camera_selected.connect(self.camera_selected)
        self.camera_controls.resolution_selected.connect(self.resolution_selected)
        self.plot_controls.x_axis_limits_changed.connect(self.x_axis_limits_changed)
        self.plot_controls.y_axis_limits_changed.connect(self.y_axis_limits_changed)
        self.plot_controls.export_plot_image_requested.connect(self.export_plot_image_requested)

    def update_connection_status(self, text, connected):
        self.conn_lbl.setText(text)
        color = "#A3BE8C" if connected else "#BF616A"
        self.conn_lbl.setStyleSheet(f"font-weight:bold;color:{color};")

    def update_prim_data(self, idx, t_dev, p_dev):
        self.idx_lbl.setText(str(idx))
        self.time_lbl.setText(f"{t_dev:.2f}")
        self.pres_lbl.setText(f"{p_dev:.2f} mmHg")

    def update_camera_resolutions(self, res_list):
        self.camera_controls.update_resolutions(res_list)
class PressurePlotWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color:white;")
        layout = QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)

        self.fig = Figure(facecolor="white")
        self.ax  = self.fig.add_subplot(111)
        self.ax.set_facecolor("#ECEFF4")
        self.ax.set_xlabel("Time (s)", color="#333333", fontsize=10)
        self.ax.set_ylabel("Pressure (mmHg)", color="#333333", fontsize=10)
        self.ax.tick_params(colors="#333333", labelsize=9)
        for spine in ["bottom","left","top","right"]:
            self.ax.spines[spine].set_color("#333333")
        self.line, = self.ax.plot([], [], "-", lw=1.5, color="#D6C832")

        self.canvas = FigureCanvas(self.fig)
        layout.addWidget(self.canvas)

        self.times, self.pressures = [], []
        self.max_pts     = PLOT_MAX_POINTS
        self.manual_xlim = None
        self.manual_ylim = (PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)
        self.ax.set_ylim(self.manual_ylim)
        self.fig.tight_layout(pad=0.5)

    def update_plot(self, t, p, auto_x, auto_y):
        self.times.append(t); self.pressures.append(p)
        if len(self.times) > self.max_pts:
            self.times = self.times[-self.max_pts:]
            self.pressures = self.pressures[-self.max_pts:]
        if not self.times:
            self.canvas.draw_idle()
            return
        self.line.set_data(self.times, self.pressures)

        # X-axis
        if auto_x:
            if len(self.times) > 1:
                rng = self.times[-1] - self.times[0]
                pad = max(1, rng*0.05)
                self.ax.set_xlim(self.times[0] - pad*0.1, self.times[-1] + pad*0.9)
            else:
                self.ax.set_xlim(self.times[0]-0.5, self.times[0]+0.5)
            self.manual_xlim = None
        elif self.manual_xlim:
            self.ax.set_xlim(self.manual_xlim)

        # Y-axis
        if auto_y:
            if self.pressures:
                mn, mx = min(self.pressures), max(self.pressures)
                rng = mx - mn
                pad = rng*0.1 if rng>0 else 5
                pad = max(pad,5)
                self.ax.set_ylim(mn-pad, mx+pad)
            self.manual_ylim = None
        elif self.manual_ylim:
            self.ax.set_ylim(self.manual_ylim)

        self.canvas.draw_idle()

    def set_manual_x_limits(self, xmin, xmax):
        if xmin < xmax:
            self.manual_xlim = (xmin, xmax)
            self.ax.set_xlim(self.manual_xlim)
        else:
            log.warning("X min must be less than X max.")
        self.canvas.draw_idle()

    def set_manual_y_limits(self, ymin, ymax):
        if ymin < ymax:
            self.manual_ylim = (ymin, ymax)
            self.ax.set_ylim(self.manual_ylim)
        else:
            log.warning("Y min must be less than Y max.")
        self.canvas.draw_idle()

    def reset_zoom(self, auto_x, auto_y):
        self.manual_xlim = None
        self.manual_ylim = (PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)
        if auto_x and self.times:
            if len(self.times)>1:
                rng = self.times[-1] - self.times[0]
                pad = max(1, rng*0.05)
                self.ax.set_xlim(self.times[0]-pad*0.1, self.times[-1]+pad*0.9)
            else:
                self.ax.set_xlim(self.times[0]-0.5, self.times[0]+0.5)
        if auto_y and self.pressures:
            mn, mx = min(self.pressures), max(self.pressures)
            rng = mx - mn
            pad = max(rng*0.1, 5)
            self.ax.set_ylim(mn-pad, mx+pad)
        else:
            self.ax.set_ylim(PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)
        self.canvas.draw_idle()

    def clear_plot(self):
        self.times.clear(); self.pressures.clear()
        self.line.set_data([], [])
        self.ax.relim()
        self.ax.set_xlim(0,10)
        self.ax.set_ylim(PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)
        self.canvas.draw_idle()

    def export_as_image(self):
        if not self.fig.axes:
            QMessageBox.warning(self, "Empty Plot", "Cannot export an empty plot.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Plot Image", "",
            "PNG (*.png);;JPEG (*.jpg *.jpeg);;SVG (*.svg);;PDF (*.pdf)"
        )
        if path:
            try:
                self.fig.savefig(path, dpi=300, facecolor=self.fig.get_facecolor())
                log.info(f"Plot saved to {path}")
                bar = self.parent().statusBar() if self.parent() else None
                if bar:
                    bar.showMessage(f"Plot exported to {os.path.basename(path)}", 3000)
            except Exception as e:
                log.error("Error saving plot image", exc_info=True)
                QMessageBox.critical(self, "Export Error", f"Could not save plot image: {e}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self._base       = os.path.dirname(__file__)
        self.icon_dir    = os.path.join(self._base, "icons")
        self._serial_thread = None
        self.trial_recorder = None
        self._is_recording  = False

        # 1) Console must come first
        self._build_console()

        # 2) Central (creates top_ctrl)
        self._build_central()

        # 3) Menu (can now reference top_ctrl safely)
        self._build_menu()

        # 4) Toolbar (can now reference start/stop trial actions)
        self._build_toolbar()

        # 5) Statusbar
        self._build_statusbar()

        self.showMaximized()
        QTimer.singleShot(200, self._equalize_splitter)
        log.info(f"{APP_NAME} started.")
        self.statusBar().showMessage("Ready. Select camera and serial port.", 5000)
        self.top_ctrl.update_connection_status("Disconnected", False)

    # — Console Dock
    def _build_console(self):
        self.dock_console = QDockWidget("Console", self)
        self.dock_console.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea)
        self.dock_console.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable)
        widget = QWidget(); layout = QVBoxLayout(widget)
        self.console_out = QTextEdit(); self.console_out.setReadOnly(True)
        layout.addWidget(self.console_out)
        self.dock_console.setWidget(widget)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.dock_console)

    # — Central area (camera + plot)
    def _build_central(self):
        cw = QWidget(); v_layout = QVBoxLayout(cw)
        v_layout.setContentsMargins(5,5,5,5); v_layout.setSpacing(5)

        self.top_ctrl = TopControlPanel(self)
        v_layout.addWidget(self.top_ctrl)

        # Connect top_ctrl signals
        self.top_ctrl.camera_selected.connect(self._on_camera_device_selected)
        self.top_ctrl.resolution_selected.connect(self._on_camera_resolution_selected)
        self.top_ctrl.export_plot_image_requested.connect(lambda: self.plot_w.export_as_image())

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setStyleSheet("QSplitter::handle{background-color:#18453B;}")

        # Camera area
        cam_container = QWidget(); cam_lay = QVBoxLayout(cam_container)
        cam_lay.setContentsMargins(0,0,0,0)
        self.qt_cam = QtCameraWidget(parent=self)
        self.qt_cam.frame_ready.connect(self._on_frame_ready)
        self.qt_cam.camera_error.connect(self._on_camera_error)
        self.qt_cam.camera_resolutions_updated.connect(self.top_ctrl.update_camera_resolutions)
        cam_lay.addWidget(self.qt_cam)
        self.splitter.addWidget(cam_container)

        # Plot area
        self.plot_w = PressurePlotWidget()
        self.splitter.addWidget(self.plot_w)

        # Wire plot-control buttons
        self.top_ctrl.plot_controls.reset_btn.clicked.connect(
            lambda: self.plot_w.reset_zoom(
                self.top_ctrl.plot_controls.auto_x_cb.isChecked(),
                self.top_ctrl.plot_controls.auto_y_cb.isChecked()
            )
        )
        self.top_ctrl.plot_controls.x_axis_limits_changed.connect(self.plot_w.set_manual_x_limits)
        self.top_ctrl.plot_controls.y_axis_limits_changed.connect(self.plot_w.set_manual_y_limits)

        v_layout.addWidget(self.splitter, 1)
        self.setCentralWidget(cw)

        # Populate cameras and then resolutions
        QTimer.singleShot(0, self.top_ctrl.camera_controls.populate_camera_selector)

    # ──────────────────────────────────────────────────────────────────────
    # Slots for camera panel signals
    def _on_camera_device_selected(self, camera_id: int):
        log.info(f"Camera device selected in MainWindow: {camera_id}")
        if self.qt_cam:
            self.qt_cam.set_active_camera(camera_id)
        else:
            log.error("qt_cam widget not initialized")

    def _on_camera_resolution_selected(self, resolution_str: str):
        log.info(f"Camera resolution selected in MainWindow: {resolution_str}")
        if not self.qt_cam:
            log.error("qt_cam widget not initialized")
            return

        try:
            w, h = map(int, resolution_str.split('x'))
            self.qt_cam.set_active_resolution(w, h)
        except ValueError:
            log.error(f"Invalid resolution string: {resolution_str}")


    # — Application menu
    def _build_menu(self):
        mb = self.menuBar()

        # File ► Export Data & Image, Exit
        file_menu = mb.addMenu("&File")
        exp_data = QAction(QIcon(os.path.join(self.icon_dir,"csv.svg")), "Export Plot &Data…", self)
        exp_data.triggered.connect(self._on_export_plot_data_csv)
        file_menu.addAction(exp_data)

        exp_img  = QAction(QIcon(os.path.join(self.icon_dir,"image.svg")), "Export Plot &Image…", self)
        exp_img.triggered.connect(lambda: self.plot_w.export_as_image())
        file_menu.addAction(exp_img)

        file_menu.addSeparator()
        exit_act = QAction(QIcon(os.path.join(self.icon_dir,"exit.svg")), "&Exit", self)
        exit_act.setShortcut(QKeySequence(Qt.ControlModifier|Qt.Key_Q))
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)

        # Acquisition ► Start/Stop trial (created here so toolbar can reference)
        acq_menu = mb.addMenu("&Acquisition")
        self.start_trial_action = QAction(QIcon(os.path.join(self.icon_dir,"record.svg")), "Start PC Recording", self)
        self.start_trial_action.setShortcut(QKeySequence(Qt.ControlModifier|Qt.Key_R))
        self.start_trial_action.triggered.connect(self._start_pc_recording)
        self.start_trial_action.setEnabled(False)
        acq_menu.addAction(self.start_trial_action)

        self.stop_trial_action = QAction(QIcon(os.path.join(self.icon_dir,"stop.svg")), "Stop PC Recording", self)
        self.stop_trial_action.setShortcut(QKeySequence(Qt.ControlModifier|Qt.Key_T))
        self.stop_trial_action.triggered.connect(self._stop_pc_recording)
        self.stop_trial_action.setEnabled(False)
        acq_menu.addAction(self.stop_trial_action)

        # View ► Toggle console
        view_menu = mb.addMenu("&View")
        tog = self.dock_console.toggleViewAction()
        tog.setText("Toggle Console"); tog.setIcon(QIcon(os.path.join(self.icon_dir,"console.svg")))
        view_menu.addAction(tog)

        # Plot ► Clear & Reset Zoom
        plot_menu = mb.addMenu("&Plot")
        clear_act = QAction(QIcon(os.path.join(self.icon_dir,"clear_plot.svg")), "Clear Plot Data", self)
        clear_act.triggered.connect(self._on_clear_plot)
        plot_menu.addAction(clear_act)

        reset_act = QAction(QIcon(os.path.join(self.icon_dir,"reset_zoom.svg")), "Reset Zoom", self)
        reset_act.triggered.connect(self.top_ctrl.plot_controls.reset_btn.click)
        plot_menu.addAction(reset_act)

        # Help ► About
        help_menu = mb.addMenu("&Help")
        about_act = QAction(QIcon(os.path.join(self.icon_dir,"about.svg")), "&About", self)
        about_act.triggered.connect(self._on_about)
        help_menu.addAction(about_act)

        qt_act = QAction("About &Qt", self)
        qt_act.triggered.connect(QApplication.instance().aboutQt)
        help_menu.addAction(qt_act)

    # — Toolbar (uses start/stop actions from menu)
    def _build_toolbar(self):
        tb = QToolBar("Main Controls")
        tb.setIconSize(QSize(22,22))
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(Qt.TopToolBarArea, tb)

        self.act_connect = QAction(QIcon(os.path.join(self.icon_dir,"plug.svg")), "&Connect", self)
        self.act_connect.setToolTip("Connect to PRIM device")
        self.act_connect.triggered.connect(self._toggle_serial)
        tb.addAction(self.act_connect)

        self.port_combo = QComboBox()
        self.port_combo.setToolTip("Select Serial Port")
        self.port_combo.setMinimumWidth(200)
        self.port_combo.addItem("🔧 Simulated Data", None)
        try:
            for p, d in list_serial_ports():
                self.port_combo.addItem(f"{p} ({d or 'Serial Port'})", p)
        except Exception:
            log.error("Error listing serial ports", exc_info=True)
        tb.addWidget(self.port_combo)

        tb.addSeparator()
        tb.addAction(self.start_trial_action)
        tb.addAction(self.stop_trial_action)
        tb.addSeparator()
        tb.addAction(self._on_clear_plot.__self__.clear_plot_action if False else getattr(self, 'clear_plot_action', QAction()))
        # (You can similarly wire export-image here if desired)
        self.open_last_trial_folder_action = QAction(
            QIcon(os.path.join(self.icon_dir,"folder_open.svg")), "Open Last Trial Folder", self
        )
        self.open_last_trial_folder_action.triggered.connect(self._open_last_trial_folder)
        self.open_last_trial_folder_action.setEnabled(False)
        tb.addAction(self.open_last_trial_folder_action)

    # — Status bar with elapsed time
    def _build_statusbar(self):
        sb = self.statusBar() or QStatusBar(); self.setStatusBar(sb)
        self.app_time_lbl = QLabel("App Time: 00:00:00")
        sb.addPermanentWidget(self.app_time_lbl)

        self._app_elapsed_seconds = 0
        timer = QTimer(self); timer.setInterval(1000)
        timer.timeout.connect(self._tick_app_elapsed_time)
        timer.start()

    # — Splitter resizing
    def _equalize_splitter(self):
        try:
            total = self.splitter.width()
            self.splitter.setSizes([int(total*0.6), int(total*0.4)])
        except Exception as e:
            log.warning(f"Could not equalize splitter: {e}")

    # ——————————————————————————————————————————————————————————
    # Serial / PRIM device
    def _toggle_serial(self):
        sb = self.statusBar()
        if not self._serial_thread or not self._serial_thread.isRunning():
            port = self.port_combo.currentData()
            try:
                self._serial_thread = SerialThread(port=port, parent=self)
                self._serial_thread.data_ready.connect(self._on_serial_data_ready)
                self._serial_thread.error_occurred.connect(self._on_serial_error)
                self._serial_thread.status_changed.connect(self._on_serial_status)
                self._serial_thread.finished.connect(self._on_serial_thread_finished)
                self._serial_thread.start()
                sb.showMessage(f"Connecting to {port or 'simulation'}...", 3000)
            except Exception:
                log.error("Failed to start SerialThread", exc_info=True)
                QMessageBox.critical(self, "Serial Error",
                                     "Could not start serial thread.")
                self._serial_thread = None
                self.top_ctrl.update_connection_status("Error", False)
        else:
            self._serial_thread.stop()

    def _on_serial_status(self, msg: str):
        self.statusBar().showMessage(f"PRIM Status: {msg}", 5000)
        log.info(f"Serial Status: {msg}")
        connected = "Connected" in msg or "simulation mode" in msg
        self.top_ctrl.update_connection_status(msg if connected else "Disconnected", connected)
        icon = "plug-disconnect.svg" if connected else "plug.svg"
        self.act_connect.setIcon(QIcon(os.path.join(self.icon_dir, icon)))
        self.act_connect.setText("Disconnect PRIM" if connected else "Connect to PRIM")
        self.start_trial_action.setEnabled(connected)
        if not connected and self._is_recording:
            self._stop_pc_recording()
        self.port_combo.setEnabled(not connected)

    def _on_serial_error(self, error_message: str):
        log.error(f"Serial Thread Error: {error_message}")
        QMessageBox.warning(self, "PRIM Device Error", error_message)
        self.statusBar().showMessage(f"PRIM Error: {error_message}", 5000)
        self.top_ctrl.update_connection_status(f"Error: {error_message[:30]}…", False)

    def _on_serial_thread_finished(self):
        log.info("Serial thread has finished.")
        self._serial_thread = None
        self._on_serial_status("Disconnected")

    # ——————————————————————————————————————————————————————————
    # Recording trial
    def _start_pc_recording(self):
        if not self._serial_thread or not self._serial_thread.isRunning():
            QMessageBox.warning(self, "Not Connected",
                                "PRIM device not connected.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Trial Information")
        form = QFormLayout(dlg)
        self.trial_name_edit = QLineEdit(
            f"Trial_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}"
        )
        form.addRow("Trial Name/ID:", self.trial_name_edit)
        self.operator_edit = QLineEdit(); form.addRow("Operator:", self.operator_edit)
        self.sample_edit = QLineEdit(); form.addRow("Sample Details:", self.sample_edit)
        self.notes_edit = QTextEdit(); self.notes_edit.setFixedHeight(80)
        form.addRow("Notes:", self.notes_edit)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject)
        form.addRow(btns)

        if dlg.exec_() != QDialog.Accepted:
            return

        trial_name = self.trial_name_edit.text() or f"Trial_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}"
        operator = self.operator_edit.text()
        sample = self.sample_edit.text()
        notes = self.notes_edit.toPlainText()

        base_dir = os.path.join(os.path.expanduser("~"), "PRIM_Trials")
        folder_name = "".join(c if c.isalnum() or c in (" ", "_", "-") else "_" for c in trial_name).rstrip()
        trial_folder = os.path.join(base_dir, folder_name)
        os.makedirs(trial_folder, exist_ok=True)
        base_save = os.path.join(trial_folder, folder_name)

        try:
            # Determine resolution
            fw, fh = DEFAULT_FRAME_SIZE
            if hasattr(self.qt_cam, "get_current_resolution"):
                res = self.qt_cam.get_current_resolution()
                if res and not res.isEmpty():
                    fw, fh = res.width(), res.height()

            log.info(f"Starting trial recording with frame size: {fw}x{fh}")
            self.trial_recorder = TrialRecorder(
                base_save, fps=DEFAULT_FPS, frame_size=(fw, fh),
                video_codec=DEFAULT_VIDEO_CODEC, video_ext=DEFAULT_VIDEO_EXTENSION
            )
            if not self.trial_recorder.is_recording:
                raise RuntimeError("TrialRecorder failed to initialize.")

            self.last_trial_basepath = os.path.dirname(self.trial_recorder.basepath_with_ts)
            self.open_last_trial_folder_action.setEnabled(True)

            meta = f"{self.trial_recorder.basepath_with_ts}_metadata.txt"
            with open(meta, "w") as mf:
                mf.write(
                    f"Trial Name: {trial_name}\n"
                    f"Date: {QDateTime.currentDateTime().toString('yyyy-MM-dd HH:mm:ss')}\n"
                    f"Operator: {operator}\n"
                    f"Sample Details: {sample}\n"
                    f"FPS Target: {DEFAULT_FPS}\n"
                    f"Resolution: {fw}x{fh}\n"
                    f"Video File: {os.path.basename(self.trial_recorder.video.filename)}\n"
                    f"CSV File: {os.path.basename(self.trial_recorder.csv.filename)}\n"
                    f"Notes:\n{notes}\n"
                )
            log.info(f"Metadata saved to {meta}")

            self._is_recording = True
            self.start_trial_action.setEnabled(False)
            self.stop_trial_action.setEnabled(True)
            self.plot_w.clear_plot()
            self.statusBar().showMessage(f"PC Recording Started: {trial_name}", 0)
            log.info(f"PC recording started. Base path: {base_save}")

        except Exception:
            log.error("Failed to start PC recording", exc_info=True)
            QMessageBox.critical(self, "Recording Error", "Could not start recording.")
            if self.trial_recorder:
                self.trial_recorder.stop()
            self._is_recording = False
            self.open_last_trial_folder_action.setEnabled(False)

    def _stop_pc_recording(self):
        if self.trial_recorder:
            base = os.path.basename(self.trial_recorder.basepath_with_ts) if hasattr(self.trial_recorder, "basepath_with_ts") else "UnknownTrial"
            frames = getattr(self.trial_recorder, "video_frame_count", "N/A")
            self.trial_recorder.stop()
            log.info(f"PC recording stopped. Video frames: {frames}")
            self.statusBar().showMessage(f"PC Recording Stopped: {base}", 5000)
            self.trial_recorder = None
        self._is_recording = False
        connected = self._serial_thread and self._serial_thread.isRunning()
        self.start_trial_action.setEnabled(connected)
        self.stop_trial_action.setEnabled(False)

    # ——————————————————————————————————————————————————————————
    # Handle incoming serial data
    def _on_serial_data_ready(self, idx, t_dev, p_dev):
        self.top_ctrl.update_prim_data(idx, t_dev, p_dev)
        auto_x = self.top_ctrl.plot_controls.auto_x_cb.isChecked()
        auto_y = self.top_ctrl.plot_controls.auto_y_cb.isChecked()
        self.plot_w.update_plot(t_dev, p_dev, auto_x, auto_y)

        if self.console_out:
            line = f"PRIM Data: Idx={idx}, Time={t_dev:.3f}s, Pressure={p_dev:.2f} mmHg"
            self.console_out.append(line)
            doc = self.console_out.document()
            if doc and doc.lineCount() > 200:
                cursor = self.console_out.textCursor()
                cursor.movePosition(QTextCursor.Start)
                cursor.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor,
                                    doc.lineCount() - 200)
                cursor.removeSelectedText()
                cursor.movePosition(QTextCursor.End)
                self.console_out.setTextCursor(cursor)
            sb = self.console_out.verticalScrollBar()
            if sb:
                sb.setValue(sb.maximum())

        if self._is_recording:
            try:
                self.trial_recorder.write_csv_data(t_dev, idx, p_dev)
            except Exception:
                log.error("Error writing CSV data", exc_info=True)
                self._stop_pc_recording()
                self.statusBar().showMessage("ERROR: CSV recording failed.", 5000)

    # ——————————————————————————————————————————————————————————
    def _tick_app_elapsed_time(self):
        self._app_elapsed_seconds += 1
        h = self._app_elapsed_seconds // 3600
        m = (self._app_elapsed_seconds % 3600) // 60
        s = self._app_elapsed_seconds % 60
        self.app_time_lbl.setText(f"App Time: {h:02}:{m:02}:{s:02}")

    def _on_clear_plot(self):
        self.plot_w.clear_plot()
        self.statusBar().showMessage("Plot data cleared.", 3000)

    def _on_export_plot_data_csv(self):
        if not self.plot_w.times:
            QMessageBox.information(self, "No Data", "No data in plot to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Plot Data As CSV…",
            "plot_data.csv", "CSV Files (*.csv)"
        )
        if not path:
            return
        try:
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["time_s", "pressure_mmHg"])
                for t, p in zip(self.plot_w.times, self.plot_w.pressures):
                    writer.writerow([f"{t:.3f}", f"{p:.2f}"])
            self.statusBar().showMessage(
                f"Plot data exported to {os.path.basename(path)}", 3000
            )
            log.info(f"Plot data exported to {path}")
        except Exception:
            log.error("Error exporting plot data", exc_info=True)
            QMessageBox.critical(self, "Export Error", "Could not export plot data.")

    def _open_last_trial_folder(self):
        if getattr(self, "last_trial_basepath", None) and os.path.isdir(self.last_trial_basepath):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_trial_basepath))
            log.info(f"Opened folder: {self.last_trial_basepath}")
        else:
            QMessageBox.information(self, "No Folder", "No previous trial folder recorded.")
            log.warning(f"Could not open last trial folder: {getattr(self, 'last_trial_basepath', None)}")

    def _on_about(self):
        QMessageBox.about(self, f"About {APP_NAME}", ABOUT_TEXT)

    def closeEvent(self, ev):
        # (… your existing cleanup code …)
        super().closeEvent(ev)
