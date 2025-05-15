import sys
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
from PyQt5 import QtCore
from PyQt5.QtCore import Qt, QTimer, QSize, pyqtSignal, QDateTime, QCoreApplication, QUrl
from PyQt5.QtGui import QIcon, QFont, QImage, QPixmap, QPalette, QColor, QTextCursor, QKeySequence, QDesktopServices
from PyQt5.QtMultimedia import QCameraInfo # For CameraControlPanel

from threads.qtcamera_widget import QtCameraWidget
from threads.serial_thread import SerialThread
from recording import TrialRecorder
# utils.list_cameras uses OpenCV, QCameraInfo is for Qt Multimedia cameras.
# We will primarily use QCameraInfo for selecting cameras for QtCameraWidget.
from utils import list_serial_ports # list_cameras can be kept for other purposes if needed

from config import (
    DEFAULT_VIDEO_CODEC, DEFAULT_VIDEO_EXTENSION, DEFAULT_FPS, DEFAULT_FRAME_SIZE,
    DEFAULT_CAMERA_INDEX, # AVAILABLE_RESOLUTIONS is now dynamic via QtCameraWidget
    APP_NAME, APP_VERSION, ABOUT_TEXT, LOG_LEVEL,
    PLOT_MAX_POINTS, PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
# import numpy as np # Uncomment if/when using qimage_to_bgr_numpy
# import cv2         # Uncomment if/when using qimage_to_bgr_numpy

numeric_log_level_main = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(level=numeric_log_level_main,
                    format='%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] %(threadName)s - %(message)s')
log = logging.getLogger(__name__)

class CameraControlPanel(QGroupBox):
    camera_selected = pyqtSignal(int)
    resolution_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__("Camera", parent)
        cam_layout = QFormLayout(self); cam_layout.setSpacing(8)
        self.cam_selector = QComboBox(); self.cam_selector.setToolTip("Select available camera")
        self.populate_camera_selector() # Call method to populate
        self.cam_selector.currentIndexChanged.connect(self._on_camera_selected_changed)
        cam_layout.addRow("Device:", self.cam_selector)
        
        self.res_selector = QComboBox(); self.res_selector.setToolTip("Select camera resolution") # Defined here
        self.res_selector.currentIndexChanged.connect(self._on_resolution_selected_changed)
        cam_layout.addRow("Resolution:", self.res_selector); self.res_selector.setEnabled(False)
        
        self.exposure_slider = QSlider(QtCore.Qt.Horizontal); self.exposure_slider.setEnabled(False); cam_layout.addRow("Exposure:", self.exposure_slider)
        self.gain_slider = QSlider(QtCore.Qt.Horizontal); self.gain_slider.setEnabled(False); cam_layout.addRow("Gain:", self.gain_slider)
        self.brightness_slider = QSlider(QtCore.Qt.Horizontal); self.brightness_slider.setEnabled(False); cam_layout.addRow("Brightness:", self.brightness_slider)

    def populate_camera_selector(self):
        self.cam_selector.clear()
        try:
            cameras_info = QCameraInfo.availableCameras() # Uses the new import
            if cameras_info:
                for i, cam_info in enumerate(cameras_info):
                    self.cam_selector.addItem(cam_info.description() or f"Camera {i}", i) # Store index as data
                
                # Attempt to set to configured default camera index
                # Note: DEFAULT_CAMERA_INDEX is an integer index.
                if 0 <= DEFAULT_CAMERA_INDEX < self.cam_selector.count():
                    self.cam_selector.setCurrentIndex(DEFAULT_CAMERA_INDEX)
                elif self.cam_selector.count() > 0: # Fallback to first camera
                    self.cam_selector.setCurrentIndex(0)
                
                # Emit signal for initial selection if a camera is actually selected
                if self.cam_selector.currentIndex() != -1: # Check if a valid item is selected
                     self._on_camera_selected_changed(self.cam_selector.currentIndex()) # Trigger initial load

            else:
                self.cam_selector.addItem("No Qt cameras found", -1); self.cam_selector.setEnabled(False)
        except Exception as e:
            log.error(f"Error listing Qt cameras: {e}", exc_info=True)
            self.cam_selector.addItem("Error listing cameras", -1); self.cam_selector.setEnabled(False)

    def _on_camera_selected_changed(self, index):
        camera_id = self.cam_selector.itemData(index) # itemData is the index 'i'
        if camera_id is not None and camera_id != -1:
            self.camera_selected.emit(camera_id)
            if hasattr(self, 'res_selector'): # Check if res_selector exists
                self.res_selector.clear()
                self.res_selector.setEnabled(False)

    def _on_resolution_selected_changed(self, index):
        res_str = self.res_selector.itemData(index)
        if res_str: self.resolution_selected.emit(res_str)

    def update_resolutions(self, res_list: list):
        if not hasattr(self, 'res_selector'): return
        current_res_data = self.res_selector.currentData()
        self.res_selector.clear()
        if res_list:
            for res_str_item in res_list: self.res_selector.addItem(res_str_item, res_str_item)
            self.res_selector.setEnabled(True)
            if current_res_data and self.res_selector.findData(current_res_data) != -1:
                self.res_selector.setCurrentIndex(self.res_selector.findData(current_res_data))
            elif DEFAULT_FRAME_SIZE: # Fallback to config default if previous selection not in new list
                 default_res_str_item = f"{DEFAULT_FRAME_SIZE[0]}x{DEFAULT_FRAME_SIZE[1]}"
                 idx = self.res_selector.findText(default_res_str_item)
                 if idx != -1: self.res_selector.setCurrentIndex(idx)
        else: self.res_selector.addItem("N/A", None); self.res_selector.setEnabled(False)

class PlotControlPanel(QGroupBox): # Extracted
    # Signals for plot customization
    x_axis_limits_changed = pyqtSignal(float, float)
    y_axis_limits_changed = pyqtSignal(float, float)
    export_plot_image_requested = pyqtSignal()
    # ... more signals for line style, color etc. ...

    def __init__(self, parent=None):
        super().__init__("Plot", parent)
        plot_layout = QFormLayout(self)
        plot_layout.setSpacing(8)

        self.auto_x_cb = QCheckBox("Auto-scale X"); self.auto_x_cb.setChecked(True)
        plot_layout.addRow(self.auto_x_cb)
        self.x_min_spin = QDoubleSpinBox(); self.x_min_spin.setEnabled(False); self.x_min_spin.setDecimals(1)
        self.x_max_spin = QDoubleSpinBox(); self.x_max_spin.setEnabled(False); self.x_max_spin.setDecimals(1)
        x_lim_layout = QHBoxLayout(); x_lim_layout.addWidget(QLabel("Min:")); x_lim_layout.addWidget(self.x_min_spin)
        x_lim_layout.addWidget(QLabel("Max:")); x_lim_layout.addWidget(self.x_max_spin)
        plot_layout.addRow("X-Limits:", x_lim_layout)

        self.auto_y_cb = QCheckBox("Auto-scale Y"); self.auto_y_cb.setChecked(True)
        plot_layout.addRow(self.auto_y_cb)
        self.y_min_spin = QDoubleSpinBox(); self.y_min_spin.setEnabled(False); self.y_min_spin.setDecimals(1)
        self.y_max_spin = QDoubleSpinBox(); self.y_max_spin.setEnabled(False); self.y_max_spin.setDecimals(1)
        self.y_min_spin.setValue(PLOT_DEFAULT_Y_MIN); self.y_max_spin.setValue(PLOT_DEFAULT_Y_MAX) # Set initial from config
        y_lim_layout = QHBoxLayout(); y_lim_layout.addWidget(QLabel("Min:")); y_lim_layout.addWidget(self.y_min_spin)
        y_lim_layout.addWidget(QLabel("Max:")); y_lim_layout.addWidget(self.y_max_spin)
        plot_layout.addRow("Y-Limits:", y_lim_layout)
        
        self.reset_btn = QPushButton("↺ Reset Zoom")
        self.export_img_btn = QPushButton("Export Image")
        plot_btn_layout = QHBoxLayout()
        plot_btn_layout.addWidget(self.reset_btn)
        plot_btn_layout.addWidget(self.export_img_btn)
        plot_layout.addRow(plot_btn_layout)

        # Connections
        self.auto_x_cb.toggled.connect(lambda checked: self.x_min_spin.setEnabled(not checked) or self.x_max_spin.setEnabled(not checked))
        self.auto_y_cb.toggled.connect(lambda checked: self.y_min_spin.setEnabled(not checked) or self.y_max_spin.setEnabled(not checked))
        self.x_min_spin.valueChanged.connect(self._emit_x_limits)
        self.x_max_spin.valueChanged.connect(self._emit_x_limits)
        self.y_min_spin.valueChanged.connect(self._emit_y_limits)
        self.y_max_spin.valueChanged.connect(self._emit_y_limits)
        self.export_img_btn.clicked.connect(self.export_plot_image_requested)

    def _emit_x_limits(self):
        if not self.auto_x_cb.isChecked():
            self.x_axis_limits_changed.emit(self.x_min_spin.value(), self.x_max_spin.value())
    def _emit_y_limits(self):
        if not self.auto_y_cb.isChecked():
            self.y_axis_limits_changed.emit(self.y_min_spin.value(), self.y_max_spin.value())


class TopControlPanel(QWidget):
    """Container for various control panels."""
    # Forward signals from sub-panels
    camera_selected = pyqtSignal(int)
    resolution_selected = pyqtSignal(str)
    x_axis_limits_changed = pyqtSignal(float, float)
    y_axis_limits_changed = pyqtSignal(float, float)
    export_plot_image_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(15)

        self.camera_controls = CameraControlPanel(self)
        layout.addWidget(self.camera_controls, 1) # First third (approx)

        # --- PRIM Box Info (Display Only for v1) ---
        prim_info_box = QGroupBox("PRIM Device Status")
        prim_info_layout = QFormLayout(prim_info_box)
        prim_info_layout.setSpacing(8)
        self.connection_status_label = QLabel("Disconnected")
        self.connection_status_label.setStyleSheet("font-weight: bold; color: #D6C832;")
        prim_info_layout.addRow("Connection:", self.connection_status_label)
        self.arduino_frame_label = QLabel("N/A")
        prim_info_layout.addRow("Device Frame #:", self.arduino_frame_label)
        self.arduino_time_label = QLabel("N/A")
        prim_info_layout.addRow("Device Time (s):", self.arduino_time_label)
        self.arduino_pressure_label = QLabel("N/A")
        self.arduino_pressure_label.setStyleSheet("font-size: 14pt; font-weight: bold;")
        prim_info_layout.addRow("Current Pressure:", self.arduino_pressure_label)
        layout.addWidget(prim_info_box, 1) # Second third

        self.plot_controls = PlotControlPanel(self)
        layout.addWidget(self.plot_controls, 1) # Third

        # Connect signals from sub-panels to be emitted by TopControlPanel
        self.camera_controls.camera_selected.connect(self.camera_selected)
        self.camera_controls.resolution_selected.connect(self.resolution_selected)
        self.plot_controls.x_axis_limits_changed.connect(self.x_axis_limits_changed)
        self.plot_controls.y_axis_limits_changed.connect(self.y_axis_limits_changed)
        self.plot_controls.export_plot_image_requested.connect(self.export_plot_image_requested)

    # --- Public methods to update info ---
    def update_connection_status(self, status_text, is_connected): # Pass through
        self.connection_status_label.setText(status_text)
        if is_connected: self.connection_status_label.setStyleSheet("font-weight: bold; color: #A3BE8C;")
        else: self.connection_status_label.setStyleSheet("font-weight: bold; color: #BF616A;")

    def update_prim_data(self, frame_idx, device_time, pressure): # Pass through
        self.arduino_frame_label.setText(str(frame_idx))
        self.arduino_time_label.setText(f"{device_time:.2f}")
        self.arduino_pressure_label.setText(f"{pressure:.2f} mmHg")

    def update_camera_resolutions(self, res_list: list): # Pass through
        self.camera_controls.update_resolutions(res_list)


class PressurePlotWidget(QWidget):
    # ... (Keep as is from my previous response, with cosmetic fixes below)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: white;")
        v_layout = QVBoxLayout(self); v_layout.setContentsMargins(0,0,0,0)
        plt.style.use('seaborn-v0_8-darkgrid')
        self.fig = Figure(figsize=(5,4), dpi=100, facecolor='white') # Set facecolor
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor('#ECEFF4')
        self.ax.set_xlabel("Time (s)", color='#333333', fontsize=10)
        self.ax.set_ylabel("Pressure (mmHg)", color='#333333', fontsize=10)
        self.ax.tick_params(axis='both', colors='#333333', labelsize=9)
        for spine in ['bottom', 'left', 'top', 'right']: self.ax.spines[spine].set_color('#333333')
        self.line, = self.ax.plot([], [], '-', lw=1.5, color='#D6C832') # Spartan Gold
        self.canvas = FigureCanvas(self.fig); v_layout.addWidget(self.canvas)
        self.times = []; self.pressures = []
        self.max_points = PLOT_MAX_POINTS
        self.current_xlim_manual = None
        self.current_ylim_manual = (PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)
        if self.current_ylim_manual: self.ax.set_ylim(self.current_ylim_manual)
        self.fig.tight_layout(pad=0.5) # Add tight_layout

    def update_plot(self, t, p, auto_x, auto_y): # Keep logic but connect to manual limits from TopControlPanel
        self.times.append(t); self.pressures.append(p)
        if len(self.times) > self.max_points:
            self.times = self.times[-self.max_points:]; self.pressures = self.pressures[-self.max_points:]
        if not self.times: self.canvas.draw_idle(); return
        self.line.set_data(self.times, self.pressures)
        
        if auto_x:
            if self.times:
                if len(self.times) > 1:
                    time_range = self.times[-1] - self.times[0]; padding = max(1, time_range * 0.05)
                    self.ax.set_xlim(self.times[0] - padding*0.1, self.times[-1] + padding*0.9) # Distribute padding
                else: self.ax.set_xlim(self.times[0] - 0.5, self.times[0] + 0.5)
            self.current_xlim_manual = None
        elif self.current_xlim_manual: self.ax.set_xlim(self.current_xlim_manual)

        if auto_y:
            if self.pressures:
                min_p, max_p = min(self.pressures), max(self.pressures); range_p = max_p - min_p
                padding = range_p * 0.1 if range_p > 0 else 5; padding = max(padding, 5)
                self.ax.set_ylim(min_p - padding, max_p + padding)
            self.current_ylim_manual = None
        elif self.current_ylim_manual: self.ax.set_ylim(self.current_ylim_manual)
        
        self.ax.figure.canvas.draw_idle()

    def set_manual_x_limits(self, x_min, x_max):
        if x_min < x_max: self.current_xlim_manual = (x_min, x_max); self.ax.set_xlim(self.current_xlim_manual)
        else: log.warning("X min must be less than X max for plot limits.")
        self.ax.figure.canvas.draw_idle()

    def set_manual_y_limits(self, y_min, y_max):
        if y_min < y_max: self.current_ylim_manual = (y_min, y_max); self.ax.set_ylim(self.current_ylim_manual)
        else: log.warning("Y min must be less than Y max for plot limits.")
        self.ax.figure.canvas.draw_idle()

    def reset_zoom(self, auto_x_enabled=True, auto_y_enabled=True): # Keep similar logic
        self.current_xlim_manual = None
        self.current_ylim_manual = (PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)
        if auto_x_enabled and self.times:
            if len(self.times) > 1: time_range = self.times[-1] - self.times[0]; padding = max(1, time_range * 0.05); self.ax.set_xlim(self.times[0]-padding*0.1, self.times[-1]+padding*0.9)
            elif self.times: self.ax.set_xlim(self.times[0] - 0.5, self.times[0] + 0.5)
        if auto_y_enabled and self.pressures:
            min_p, max_p = min(self.pressures), max(self.pressures); range_p = max_p - min_p
            padding = range_p * 0.1 if range_p > 0 else 5; padding = max(padding, 5)
            self.ax.set_ylim(min_p - padding, max_p + padding)
        elif not auto_y_enabled and self.current_ylim_manual: self.ax.set_ylim(self.current_ylim_manual)
        else: self.ax.set_ylim(PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)
        self.ax.figure.canvas.draw_idle()

    def clear_plot(self): # Keep similar logic
        self.times.clear(); self.pressures.clear(); self.line.set_data([],[])
        self.ax.relim(); self.current_ylim_manual = (PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)
        if self.current_ylim_manual: self.ax.set_ylim(self.current_ylim_manual)
        else: self.ax.set_ylim(0,100)
        self.ax.set_xlim(0,10); self.ax.figure.canvas.draw_idle()

    def export_as_image(self):
        if not self.figure.axes: # Check if plot has axes (and thus content)
            QMessageBox.warning(self, "Empty Plot", "Cannot export an empty plot.")
            return
        
        filePath, _ = QFileDialog.getSaveFileName(self, "Save Plot Image", "",
                                                  "PNG (*.png);;JPEG (*.jpg *.jpeg);;SVG (*.svg);;PDF (*.pdf)")
        if filePath:
            try:
                self.figure.savefig(filePath, dpi=300, facecolor=self.figure.get_facecolor()) # Use figure's facecolor
                log.info(f"Plot saved to {filePath}")
                if self.parent(): # If it has a parent (likely MainWindow)
                    status_bar = self.parent().statusBar()
                    if status_bar: status_bar.showMessage(f"Plot exported to {os.path.basename(filePath)}", 3000)
            except Exception as e:
                log.error(f"Error saving plot image: {e}")
                QMessageBox.critical(self, "Export Error", f"Could not save plot image: {e}")

# main_window.py (Continued - MainWindow class)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self._base = os.path.dirname(__file__)
        self.icon_dir = os.path.join(self._base, "icons")
        self._serial_thread = None; self.trial_recorder = None; self._is_recording = False
        self.qt_cam = None; self.dock_console = None; self.toggle_console_action = None

        self._build_console() 
        self._build_menu()    
        self._build_toolbar() # Toolbar now uses more icons and some text
        self._build_central() # This will use the new TopControlPanel
        self._build_statusbar()

        self.showMaximized()
        QTimer.singleShot(200, self._equalize_splitter) # Increased delay slightly
        log.info(f"{APP_NAME} started.")
        status_bar = self.statusBar()
        if status_bar: status_bar.showMessage("Ready. Select camera and serial port.", 5000)
        if hasattr(self, 'top_ctrl') and self.top_ctrl: 
            self.top_ctrl.update_connection_status("Disconnected", False)

    def _build_menu(self): # Largely same, ensure connections are correct
        mb = self.menuBar();
        if not mb: return
        
        file_menu = mb.addMenu("&File")
        if file_menu:
            self.export_plot_data_action = QAction(QIcon(os.path.join(self.icon_dir, "csv.svg")), "Export Plot &Data to CSV...", self)
            self.export_plot_data_action.triggered.connect(self._on_export_plot_data_csv)
            file_menu.addAction(self.export_plot_data_action)

            self.export_plot_image_action = QAction(QIcon(os.path.join(self.icon_dir, "image.svg")), "Export Plot as &Image...", self)
            if hasattr(self, 'plot_w'): # plot_w might not be init yet if order is strict
                 self.export_plot_image_action.triggered.connect(lambda: self.plot_w.export_as_image() if self.plot_w else None)
            file_menu.addAction(self.export_plot_image_action)

            file_menu.addSeparator()
            exit_action = QAction(QIcon(os.path.join(self.icon_dir, "exit.svg")), "&Exit", self)
            exit_action.setShortcut(QKeySequence(QtCore.Qt.ControlModifier | QtCore.Qt.Key_Q))
            exit_action.triggered.connect(lambda: self.close())
            file_menu.addAction(exit_action)

        acq_menu = mb.addMenu("&Acquisition")
        if acq_menu:
            self.start_trial_action = QAction(QIcon(os.path.join(self.icon_dir, "record.svg")), "Start PC Recording", self)
            self.start_trial_action.setShortcut(QKeySequence(QtCore.Qt.ControlModifier | QtCore.Qt.Key_R))
            self.start_trial_action.triggered.connect(self._start_pc_recording)
            self.start_trial_action.setEnabled(False) # Enabled on serial connect
            acq_menu.addAction(self.start_trial_action)

            self.stop_trial_action = QAction(QIcon(os.path.join(self.icon_dir, "stop.svg")), "Stop PC Recording", self)
            self.stop_trial_action.setShortcut(QKeySequence(QtCore.Qt.ControlModifier | QtCore.Qt.Key_T))
            self.stop_trial_action.triggered.connect(self._stop_pc_recording)
            self.stop_trial_action.setEnabled(False)
            acq_menu.addAction(self.stop_trial_action)
        
        view_menu = mb.addMenu("&View")
        if view_menu and self.dock_console: 
            self.toggle_console_action = self.dock_console.toggleViewAction()
            if self.toggle_console_action:
                 self.toggle_console_action.setText("Toggle Console") 
                 self.toggle_console_action.setIcon(QIcon(os.path.join(self.icon_dir, "console.svg")))
                 view_menu.addAction(self.toggle_console_action)
        
        plot_menu = mb.addMenu("&Plot")
        if plot_menu:
            self.clear_plot_action = QAction(QIcon(os.path.join(self.icon_dir, "clear_plot.svg")), "Clear Plot Data", self)
            self.clear_plot_action.triggered.connect(self._on_clear_plot)
            plot_menu.addAction(self.clear_plot_action)
            # Add reset zoom action here too if desired, linking to top_ctrl's button or plot_w's method
            self.reset_zoom_action = QAction(QIcon(os.path.join(self.icon_dir, "reset_zoom.svg")), "Reset Plot Zoom", self)
            if hasattr(self, 'top_ctrl'): # Connect if top_ctrl exists
                self.reset_zoom_action.triggered.connect(self.top_ctrl.plot_controls.reset_btn.click)
            plot_menu.addAction(self.reset_zoom_action)


        help_menu = mb.addMenu("&Help")
        if help_menu:
            about_action = QAction(QIcon(os.path.join(self.icon_dir, "about.svg")), "&About", self)
            about_action.triggered.connect(self._on_about)
            help_menu.addAction(about_action)
            about_qt_action = QAction("About &Qt", self)
            q_app_instance = QApplication.instance()
            if q_app_instance and hasattr(q_app_instance, 'aboutQt'):
                about_qt_action.triggered.connect(q_app_instance.aboutQt)
                help_menu.addAction(about_qt_action)

    def _build_toolbar(self):
        tb = QToolBar("Main Controls")
        tb.setIconSize(QSize(22,22))
        tb.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon) # Icons and Text
        self.addToolBar(QtCore.Qt.TopToolBarArea, tb)

        self.act_connect = QAction(QIcon(os.path.join(self.icon_dir,"plug.svg")), "&Connect", self)
        self.act_connect.setToolTip("Connect to PRIM device")
        self.act_connect.triggered.connect(self._toggle_serial)
        tb.addAction(self.act_connect)

        self.port_combo = QComboBox()
        self.port_combo.setToolTip("Select Serial Port for PRIM device")
        self.port_combo.setMinimumWidth(200) # Give it some space
        self.port_combo.addItem("🔧 Simulated Data", None)
        try:
            for port, desc in list_serial_ports(): self.port_combo.addItem(f"{port} ({desc if desc else 'Serial Port'})", port)
        except Exception as e: log.error(f"Error listing serial ports: {e}")
        tb.addWidget(self.port_combo)
        
        tb.addSeparator()
        if hasattr(self, 'start_trial_action'): tb.addAction(self.start_trial_action) # Reuses menu action
        if hasattr(self, 'stop_trial_action'): tb.addAction(self.stop_trial_action)   # Reuses menu action
        
        tb.addSeparator()
        if hasattr(self, 'clear_plot_action'): tb.addAction(self.clear_plot_action) # Reuses menu action
        if hasattr(self, 'export_plot_image_action'): tb.addAction(self.export_plot_image_action)

        # Open last trial folder action
        self.open_last_trial_folder_action = QAction(QIcon(os.path.join(self.icon_dir, "folder_open.svg")), "Open &Last Trial Folder", self)
        self.open_last_trial_folder_action.triggered.connect(self._open_last_trial_folder)
        self.open_last_trial_folder_action.setEnabled(False) # Enable after first recording
        tb.addAction(self.open_last_trial_folder_action)
        self.last_trial_basepath = None


    def _build_central(self):
        # ... (This will now use the new TopControlPanel structure) ...
        cw = QWidget(); v_layout = QVBoxLayout(cw); v_layout.setContentsMargins(5,5,5,5); v_layout.setSpacing(5)
        self.top_ctrl = TopControlPanel(self) # Pass self as parent
        v_layout.addWidget(self.top_ctrl)

        # Connect signals from the new TopControlPanel
        self.top_ctrl.camera_selected.connect(self._on_camera_device_selected)
        self.top_ctrl.resolution_selected.connect(self._on_camera_resolution_selected)
        # Note: _initialize_camera now calls _update_resolution_list in qtcamera_widget
        # which then emits camera_resolutions_updated. Connect this in main_window
        # after qt_cam is initialized.

        self.splitter = QSplitter(QtCore.Qt.Horizontal)
        self.splitter.setStyleSheet("QSplitter::handle { background-color: #18453B; }")
        self.camera_view_container = QWidget(); self.camera_view_layout = QVBoxLayout(self.camera_view_container)
        self.camera_view_layout.setContentsMargins(0,0,0,0)
        # self.camera_placeholder_label is no longer needed here, qt_cam handles its own placeholder/error
        self.splitter.addWidget(self.camera_view_container)
        
        # Initialize camera widget (it will be empty or show error until a camera is picked)
        self.qt_cam = QtCameraWidget(camera_id=-1, parent=self) # Start with no camera explicitly selected
        self.qt_cam.frame_ready.connect(self._on_frame_ready)
        self.qt_cam.camera_error.connect(self._on_camera_error)
        self.qt_cam.camera_resolutions_updated.connect(self.top_ctrl.update_camera_resolutions)
        self.camera_view_layout.addWidget(self.qt_cam)

        self.plot_w = PressurePlotWidget(); self.splitter.addWidget(self.plot_w)
        
        # Connect plot customization signals from TopControlPanel to PressurePlotWidget
        self.top_ctrl.plot_controls.reset_btn.clicked.connect(
            lambda: self.plot_w.reset_zoom(self.top_ctrl.plot_controls.auto_x_cb.isChecked(), 
                                          self.top_ctrl.plot_controls.auto_y_cb.isChecked())
        )
        self.top_ctrl.plot_controls.x_axis_limits_changed.connect(self.plot_w.set_manual_x_limits)
        self.top_ctrl.plot_controls.y_axis_limits_changed.connect(self.plot_w.set_manual_y_limits)
        self.top_ctrl.plot_controls.export_plot_image_requested.connect(self.plot_w.export_as_image)


        v_layout.addWidget(self.splitter, 1); self.setCentralWidget(cw)
        # Trigger initial population of camera selector in TopControlPanel
        QTimer.singleShot(0, self.top_ctrl.camera_controls.populate_camera_selector)


    def _initialize_camera(self, camera_id): # This method name might be confusing now
        # The actual camera initialization is now handled by qt_cam.set_active_camera
        log.info(f"MainWindow: Requesting camera change to ID {camera_id}")
        if self.qt_cam:
            self.qt_cam.set_active_camera(camera_id) # This will handle setup and errors
        else:
            log.error("qt_cam widget not initialized in MainWindow.")

    def _on_camera_device_selected(self, camera_id: int): # Slot for TopControlPanel's signal
        log.info(f"Camera device selected in MainWindow: {camera_id}")
        if self.qt_cam:
            self.qt_cam.set_active_camera(camera_id)

    def _on_camera_resolution_selected(self, resolution_str: str): # Slot for TopControlPanel's signal
        log.info(f"Camera resolution selected in MainWindow: {resolution_str}")
        if self.qt_cam:
            try:
                width, height = map(int, resolution_str.split('x'))
                self.qt_cam.set_active_resolution(width, height)
            except ValueError:
                log.error(f"Invalid resolution string from TopControlPanel: {resolution_str}")
    
    def _on_camera_error(self, error_string: str, camera_id: int):
        QMessageBox.warning(self, f"Camera Error (ID: {camera_id})", error_string)
        # Potentially disable camera-dependent UI elements
        if hasattr(self, 'top_ctrl'):
            self.top_ctrl.camera_controls.res_selector.clear()
            self.top_ctrl.camera_controls.res_selector.setEnabled(False)


    def _on_frame_ready(self, qimage: QImage, bgr_frame_obj: object): # bgr_frame_obj is 'object', can be None or np.ndarray
        # Frame is displayed by QtCameraWidget. This is for recording.
        # VideoRecorder expects a BGR NumPy array.
        bgr_numpy_array = None
        if bgr_frame_obj is not None: # If qtcamera_widget already provides it
            bgr_numpy_array = bgr_frame_obj
        elif qimage and not qimage.isNull(): # Convert QImage if necessary
            # This conversion can be slow. Ideally, QtCameraWidget handles it if performance is an issue.
            # For now, doing it here if needed.
            # Ensure you have 'import cv2' and 'import numpy as np' if using this.
            # For simplicity, if VideoRecorder only takes numpy, and qtcamerawidget only gives QImage,
            # this conversion becomes essential.
            # bgr_numpy_array = qimage_to_bgr_numpy(qimage) # Uncomment if conversion is needed
            pass # For now, assume bgr_frame_obj from QtCameraWidget or VideoRecorder handles QImage

        if self._is_recording and self.trial_recorder:
            if bgr_numpy_array is not None:
                try:
                    self.trial_recorder.write_video_frame(bgr_numpy_array)
                except Exception as e:
                    log.error(f"Error writing BGR video frame: {e}", exc_info=True)
                    self._stop_pc_recording()
                    status_bar = self.statusBar()
                    if status_bar: status_bar.showMessage("ERROR: Video recording failed.", 5000)
            elif qimage and not qimage.isNull() and not bgr_numpy_array: # If only QImage is available
                # Modify VideoRecorder to accept QImage or handle conversion there
                log.debug("BGR frame not available, QImage received. VideoRecorder may need QImage support.")
                # To make this work, VideoRecorder.write_frame would need to handle QImage
                # or convert it itself. For now, we assume it needs BGR.

    def _build_console(self):
        self.dock_console = QDockWidget("Console", self)
        self.dock_console.setAllowedAreas(QtCore.Qt.BottomDockWidgetArea | QtCore.Qt.TopDockWidgetArea)
        self.dock_console.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable)
        console_widget = QWidget(); console_layout = QVBoxLayout(console_widget)
        self.console_out = QTextEdit(); self.console_out.setReadOnly(True)
        console_layout.addWidget(self.console_out)
        self.dock_console.setWidget(console_widget)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, self.dock_console)

    def _build_statusbar(self):
        status_bar = self.statusBar();
        if not status_bar: status_bar = QStatusBar(); self.setStatusBar(status_bar)
        self.app_time_lbl = QLabel("App Time: 00:00:00"); status_bar.addPermanentWidget(self.app_time_lbl)
        self._app_elapsed_seconds = 0; self._app_elapsed_timer = QTimer(self)
        self._app_elapsed_timer.setInterval(1000)
        self._app_elapsed_timer.timeout.connect(self._tick_app_elapsed_time); self._app_elapsed_timer.start()

    def _equalize_splitter(self):
        if hasattr(self, 'splitter') and self.splitter:
            try: total = self.splitter.width(); self.splitter.setSizes([int(total * 0.6), int(total * 0.4)])
            except Exception as e: log.warning(f"Could not equalize splitter: {e}")
            
    def _toggle_serial(self):
        status_bar = self.statusBar()
        if not self._serial_thread or not self._serial_thread.isRunning():
            port = self.port_combo.currentData()
            try:
                self._serial_thread = SerialThread(port=port, parent=self)
                self._serial_thread.data_ready.connect(self._on_serial_data_ready)
                self._serial_thread.error_occurred.connect(self._on_serial_error)
                self._serial_thread.status_changed.connect(self._on_serial_status)
                self._serial_thread.finished.connect(self._on_serial_thread_finished)
                self._serial_thread.start()
                if status_bar: status_bar.showMessage(f"Connecting to {port or 'simulation'}...", 3000)
            except Exception as e:
                log.error(f"Failed to create/start SerialThread: {e}", exc_info=True)
                QMessageBox.critical(self, "Serial Error", f"Could not start serial: {e}")
                self._serial_thread = None
                if hasattr(self, 'top_ctrl') and self.top_ctrl: self.top_ctrl.update_connection_status("Error", False)
        else:
            if self._serial_thread: self._serial_thread.stop()

    def _on_serial_status(self, message: str):
        status_bar = self.statusBar()
        if status_bar: status_bar.showMessage(f"PRIM Status: {message}", 5000)
        log.info(f"Serial Status: {message}")
        is_connected = "Connected" in message or "simulation mode" in message
        if hasattr(self, 'top_ctrl') and self.top_ctrl: self.top_ctrl.update_connection_status(message if is_connected else "Disconnected", is_connected)
        if is_connected:
            self.act_connect.setIcon(QIcon(os.path.join(self.icon_dir,"plug-disconnect.svg")))
            self.act_connect.setText("Disconnect PRIM"); self.act_connect.setToolTip("Disconnect from PRIM device")
            if hasattr(self, 'start_trial_action'): self.start_trial_action.setEnabled(True)
            self.port_combo.setEnabled(False)
        else:
            self.act_connect.setIcon(QIcon(os.path.join(self.icon_dir,"plug.svg")))
            self.act_connect.setText("Connect to PRIM"); self.act_connect.setToolTip("Connect to PRIM device")
            if hasattr(self, 'start_trial_action'): self.start_trial_action.setEnabled(False)
            if self._is_recording: self._stop_pc_recording()
            self.port_combo.setEnabled(True)
            if hasattr(self, 'top_ctrl') and self.top_ctrl: self.top_ctrl.update_prim_data("N/A", float('nan'), float('nan'))

    def _on_serial_error(self, error_message: str):
        log.error(f"Serial Thread Error: {error_message}")
        QMessageBox.warning(self, "PRIM Device Error", error_message)
        status_bar = self.statusBar()
        if status_bar: status_bar.showMessage(f"PRIM Error: {error_message}", 5000)
        if hasattr(self, 'top_ctrl') and self.top_ctrl: self.top_ctrl.update_connection_status(f"Error: {error_message[:30]}...", False)

    def _on_serial_thread_finished(self):
        log.info("Serial thread has finished."); self._serial_thread = None; self._on_serial_status("Disconnected")

    def _start_pc_recording(self): # Keep metadata logic
        if not self._serial_thread or not self._serial_thread.isRunning():
            QMessageBox.warning(self, "Not Connected", "PRIM device not connected. Please connect to record meaningful data.")
            # Consider if you want to allow recording video even if serial is not connected.
            # For now, let's assume serial connection is desired for a complete trial.
            # return 
        
        dialog = QDialog(self); dialog.setWindowTitle("Trial Information"); form_layout = QFormLayout(dialog)
        self.trial_name_edit = QLineEdit(f"Trial_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}")
        form_layout.addRow("Trial Name/ID:", self.trial_name_edit); self.operator_edit = QLineEdit(); form_layout.addRow("Operator:", self.operator_edit)
        self.sample_edit = QLineEdit(); form_layout.addRow("Sample Details:", self.sample_edit)
        self.notes_edit = QTextEdit(); self.notes_edit.setFixedHeight(80); form_layout.addRow("Notes:", self.notes_edit)
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept); button_box.rejected.connect(dialog.reject); form_layout.addWidget(button_box)
        if not dialog.exec_() == QDialog.Accepted: return
        trial_name = self.trial_name_edit.text() or f"Trial_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}"
        operator = self.operator_edit.text(); sample = self.sample_edit.text(); notes = self.notes_edit.toPlainText()
        default_folder_base = os.path.join(os.path.expanduser("~"), "PRIM_Trials")
        trial_folder_name = "".join(c if c.isalnum() or c in (' ', '_', '-') else '_' for c in trial_name).rstrip() # Sanitize
        trial_folder = os.path.join(default_folder_base, trial_folder_name)
        os.makedirs(trial_folder, exist_ok=True)
        base_save_path = os.path.join(trial_folder, trial_folder_name) # Recorder adds timestamp

        try:
            frame_w, frame_h = DEFAULT_FRAME_SIZE
            if self.qt_cam and hasattr(self.qt_cam, 'get_current_resolution') and self.qt_cam.get_current_resolution():
                current_res = self.qt_cam.get_current_resolution()
                if current_res and not current_res.isEmpty():
                    frame_w, frame_h = current_res.width(), current_res.height()
            
            log.info(f"Starting trial recording with frame size: {frame_w}x{frame_h}")
            self.trial_recorder = TrialRecorder(base_save_path, fps=DEFAULT_FPS, frame_size=(frame_w, frame_h), video_codec=DEFAULT_VIDEO_CODEC, video_ext=DEFAULT_VIDEO_EXTENSION)
            if not self.trial_recorder.is_recording: raise RuntimeError("TrialRecorder failed to initialize.")
            self.last_trial_basepath = os.path.dirname(self.trial_recorder.basepath_with_ts) # Store folder path
            self.open_last_trial_folder_action.setEnabled(True)

            metadata_path = f"{self.trial_recorder.basepath_with_ts}_metadata.txt"
            with open(metadata_path, 'w') as f:
                f.write(f"Trial Name: {trial_name}\nDate: {QDateTime.currentDateTime().toString('yyyy-MM-dd HH:mm:ss')}\nOperator: {operator}\nSample Details: {sample}\nFPS Target: {DEFAULT_FPS}\nResolution: {frame_w}x{frame_h}\nVideo File: {os.path.basename(self.trial_recorder.video.filename)}\nCSV File: {os.path.basename(self.trial_recorder.csv.filename)}\nNotes:\n{notes}\n")
            log.info(f"Metadata saved to {metadata_path}")
            self._is_recording = True; self.start_trial_action.setEnabled(False); self.stop_trial_action.setEnabled(True)
            if hasattr(self, 'plot_w') and self.plot_w: self.plot_w.clear_plot()
            status_bar = self.statusBar(); 
            if status_bar: status_bar.showMessage(f"PC Recording Started: {trial_name}", 0)
            log.info(f"PC recording started. Base path: {base_save_path}")
        except Exception as e:
            log.error(f"Failed to start PC recording: {e}", exc_info=True)
            QMessageBox.critical(self, "Recording Error", f"Could not start recording: {e}")
            if self.trial_recorder: self.trial_recorder.stop(); self.trial_recorder = None
            self._is_recording = False; self.open_last_trial_folder_action.setEnabled(False)

    def _stop_pc_recording(self):
        if self.trial_recorder:
            base_name = "UnknownTrial"
            if hasattr(self.trial_recorder, 'basepath_with_ts') and self.trial_recorder.basepath_with_ts:
                 base_name = os.path.basename(self.trial_recorder.basepath_with_ts)
            video_frames = self.trial_recorder.video_frame_count if hasattr(self.trial_recorder, 'video_frame_count') else "N/A"
            self.trial_recorder.stop(); log.info(f"PC recording stopped. Video frames: {video_frames}")
            status_bar = self.statusBar()
            if status_bar: status_bar.showMessage(f"PC Recording Stopped: {base_name}", 5000)
            self.trial_recorder = None
        self._is_recording = False
        is_serial_connected = self._serial_thread is not None and self._serial_thread.isRunning()
        if hasattr(self, 'start_trial_action'): self.start_trial_action.setEnabled(is_serial_connected)
        if hasattr(self, 'stop_trial_action'): self.stop_trial_action.setEnabled(False)

    def _on_serial_data_ready(self, frame_idx, t_device, p_device):
        if hasattr(self, 'top_ctrl') and self.top_ctrl: self.top_ctrl.update_prim_data(frame_idx, t_device, p_device)
        auto_x = self.top_ctrl.plot_controls.auto_x_cb.isChecked() if hasattr(self, 'top_ctrl') else True
        auto_y = self.top_ctrl.plot_controls.auto_y_cb.isChecked() if hasattr(self, 'top_ctrl') else True
        if hasattr(self, 'plot_w') and self.plot_w: self.plot_w.update_plot(t_device, p_device, auto_x, auto_y)
        if self.console_out:
            self.console_out.append(f"PRIM Data: Idx={frame_idx}, Time={t_device:.3f}s, Pressure={p_device:.2f} mmHg")
            doc = self.console_out.document()
            if doc and doc.lineCount() > 200:
                cursor = self.console_out.textCursor(); cursor.movePosition(QTextCursor.Start)
                cursor.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor, doc.lineCount() - 200)
                cursor.removeSelectedText(); cursor.movePosition(QTextCursor.End); self.console_out.setTextCursor(cursor)
            scrollbar = self.console_out.verticalScrollBar()
            if scrollbar: scrollbar.setValue(scrollbar.maximum())
        if self._is_recording and self.trial_recorder:
            try: self.trial_recorder.write_csv_data(t_device, frame_idx, p_device)
            except Exception as e:
                log.error(f"Error writing CSV data: {e}", exc_info=True); self._stop_pc_recording()
                status_bar = self.statusBar(); 
                if status_bar: status_bar.showMessage("ERROR: CSV recording failed.", 5000)

    def _tick_app_elapsed_time(self):
        self._app_elapsed_seconds += 1; hours = self._app_elapsed_seconds // 3600
        minutes = (self._app_elapsed_seconds % 3600) // 60; seconds = self._app_elapsed_seconds % 60
        self.app_time_lbl.setText(f"App Time: {hours:02}:{minutes:02}:{seconds:02}")

    def _on_clear_plot(self):
        if hasattr(self, 'plot_w') and self.plot_w: self.plot_w.clear_plot()
        status_bar = self.statusBar(); 
        if status_bar: status_bar.showMessage("Plot data cleared.", 3000)

    def _on_export_plot_data_csv(self):
        if not hasattr(self, 'plot_w') or not self.plot_w or not self.plot_w.times:
            QMessageBox.information(self, "No Data", "No data in plot to export."); return
        path, _ = QFileDialog.getSaveFileName(self, "Export Plot Data As CSV…", "plot_data.csv", "CSV Files (*.csv)")
        if not path: return
        try:
            with open(path, 'w', newline='') as f:
                writer = csv.writer(f); writer.writerow(['time_s', 'pressure_mmHg'])
                for t_val, p_val in zip(self.plot_w.times, self.plot_w.pressures): writer.writerow([f"{t_val:.3f}", f"{p_val:.2f}"])
            status_bar = self.statusBar(); 
            if status_bar: status_bar.showMessage(f"Plot data exported to {os.path.basename(path)}", 3000)
            log.info(f"Plot data exported to {path}")
        except Exception as e:
            log.error(f"Error exporting plot data: {e}", exc_info=True)
            QMessageBox.critical(self, "Export Error", f"Could not export plot data: {e}")

    def _open_last_trial_folder(self):
        if self.last_trial_basepath and os.path.isdir(self.last_trial_basepath):
            # Use QDesktopServices to open the folder in a platform-independent way
            from PyQt5.QtGui import QDesktopServices # Local import
            from PyQt5.QtCore import QUrl # Local import
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_trial_basepath))
            log.info(f"Opened folder: {self.last_trial_basepath}")
        else:
            QMessageBox.information(self, "No Folder", "No previous trial folder recorded in this session, or folder not found.")
            log.warning(f"Could not open last trial folder: {self.last_trial_basepath}")


    def _on_about(self): QMessageBox.about(self, f"About {APP_NAME}", ABOUT_TEXT) # Keep as is

    def closeEvent(self, ev):
        log.info("Close event: Cleaning up...")
        if self._is_recording:
            reply = QMessageBox.question(self, "Recording Active", "PC Recording is active. Stop and exit?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes: self._stop_pc_recording()
            else: ev.ignore(); return
        if self._serial_thread and self._serial_thread.isRunning(): self._serial_thread.stop()
        if self.qt_cam and hasattr(self.qt_cam, 'stop_camera_resources'): self.qt_cam.stop_camera_resources() # Use the more robust stop
        super().closeEvent(ev); log.info(f"{APP_NAME} is shutting down.")


if __name__ == "__main__":
    if hasattr(QtCore.Qt, 'AA_EnableHighDpiScaling'): QCoreApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    if hasattr(QtCore.Qt, 'AA_UseHighDpiPixmaps'): QCoreApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    qss_path = os.path.join(os.path.dirname(__file__), "style.qss")
    if os.path.exists(qss_path):
        with open(qss_path, "r") as f: app.setStyleSheet(f.read()); log.info("Stylesheet loaded for direct run.")
    else:
        log.warning(f"style.qss not found at {qss_path}. Using default Fusion style.")
        app.setStyle(QStyleFactory.create("Fusion"))
        pal = QPalette(); pal.setColor(QPalette.Window, QColor(250,250,250))
        pal.setColor(QPalette.WindowText, QtCore.Qt.black); pal.setColor(QPalette.Base, QColor(240,240,240))
        pal.setColor(QPalette.AlternateBase, QColor(250,250,250)); pal.setColor(QPalette.ToolTipBase, QtCore.Qt.black)
        pal.setColor(QPalette.ToolTipText, QtCore.Qt.black); pal.setColor(QPalette.Text, QtCore.Qt.black)
        pal.setColor(QPalette.Button, QColor(245,245,245)); pal.setColor(QPalette.ButtonText, QtCore.Qt.black)
        pal.setColor(QPalette.Highlight, QColor(51,153,255)); pal.setColor(QPalette.HighlightedText, QtCore.Qt.white)
        app.setPalette(pal)
    try:
        w = MainWindow(); w.show()
    except Exception as e:
        log.critical(f"Failed to create MainWindow in direct run: {e}", exc_info=True)
        QMessageBox.critical(None, "Application Error", f"Startup error: {e}\nCheck logs.")
        sys.exit(1)
    sys.exit(app.exec_())