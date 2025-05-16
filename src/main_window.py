import os
import logging
import csv

from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QLabel,
    QMessageBox,
    QSplitter,
    QHBoxLayout,
    QVBoxLayout,
    QToolBar,
    QAction,
    QComboBox,
    QFileDialog,
    QDockWidget,
    QTextEdit,
    QLineEdit,
    QPushButton,
    QStatusBar,
    QDialog,
    QFormLayout,
    QDialogButtonBox,
    QSpinBox,
    QDoubleSpinBox,
    QSizePolicy,
    QCheckBox,
    QGroupBox,
    QSlider,
    QStyleFactory,
    QTabWidget,  # Added QTabWidget
)
from PyQt5.QtCore import Qt, QTimer, QSize, pyqtSignal, QDateTime, QUrl, pyqtSlot
from PyQt5.QtGui import (
    QIcon,
    QImage,
    QPixmap,
    QPalette,
    QColor,
    QTextCursor,
    QKeySequence,
    QDesktopServices,
    QFont,
)
from PyQt5.QtMultimedia import QCameraInfo

from threads.qtcamera_widget import QtCameraWidget
from threads.serial_thread import SerialThread
from recording import TrialRecorder
from utils import list_serial_ports

from config import (
    DEFAULT_VIDEO_CODEC,
    DEFAULT_VIDEO_EXTENSION,
    DEFAULT_FPS,
    DEFAULT_FRAME_SIZE,
    DEFAULT_CAMERA_INDEX,
    APP_NAME,
    APP_VERSION,
    ABOUT_TEXT,
    LOG_LEVEL,
    PLOT_MAX_POINTS,
    PLOT_DEFAULT_Y_MIN,
    PLOT_DEFAULT_Y_MAX,
    PRIM_RESULTS_DIR,
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# Module logger (root configured in prim_app.py)
numeric_log_level_main = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(
    level=numeric_log_level_main,
    format="%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] %(threadName)s - %(message)s",
)
log = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
class CameraControlPanel(QGroupBox):
    camera_selected = pyqtSignal(int, str)  # Emits id and description
    resolution_selected = pyqtSignal(str)
    exposure_changed = pyqtSignal(int)
    gain_changed = pyqtSignal(int)
    brightness_changed = pyqtSignal(int)
    auto_exposure_toggled = pyqtSignal(bool)
    roi_changed = pyqtSignal(int, int, int, int)
    roi_reset_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Camera", parent)
        # Main layout for the camera panel
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)  # Reduced margins
        main_layout.setSpacing(5)  # Reduced spacing

        # Tab widget for organizing controls
        tab_widget = QTabWidget()

        # -- Basic Controls Tab --
        basic_controls_widget = QWidget()
        basic_layout = QFormLayout(basic_controls_widget)
        basic_layout.setSpacing(6)  # Reduced spacing
        basic_layout.setContentsMargins(0, 0, 0, 0)

        self.cam_selector = QComboBox()
        self.cam_selector.setToolTip("Select available camera")
        self.cam_selector.currentIndexChanged.connect(self._on_camera_selected_changed)
        basic_layout.addRow("Device:", self.cam_selector)

        self.res_selector = QComboBox()
        self.res_selector.setToolTip("Select camera resolution")
        self.res_selector.currentIndexChanged.connect(
            self._on_resolution_selected_changed
        )
        self.res_selector.setEnabled(False)
        basic_layout.addRow("Resolution:", self.res_selector)

        tab_widget.addTab(basic_controls_widget, "Basic")

        # -- Advanced Controls Tab --
        advanced_controls_widget = QWidget()
        advanced_layout = QFormLayout(advanced_controls_widget)
        advanced_layout.setSpacing(6)
        advanced_layout.setContentsMargins(0, 0, 0, 0)

        self.exposure_slider = QSlider(Qt.Horizontal)
        self.exposure_value_label = QLabel("N/A")
        exposure_layout = QHBoxLayout()
        exposure_layout.addWidget(self.exposure_slider)
        exposure_layout.addWidget(self.exposure_value_label)
        advanced_layout.addRow("Exposure:", exposure_layout)

        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_value_label = QLabel("N/A")
        gain_layout = QHBoxLayout()
        gain_layout.addWidget(self.gain_slider)
        gain_layout.addWidget(self.gain_value_label)
        advanced_layout.addRow("Gain:", gain_layout)

        self.brightness_slider = QSlider(Qt.Horizontal)
        self.brightness_value_label = QLabel("N/A")
        brightness_layout = QHBoxLayout()
        brightness_layout.addWidget(self.brightness_slider)
        brightness_layout.addWidget(self.brightness_value_label)
        advanced_layout.addRow("Brightness:", brightness_layout)

        self.auto_exposure_cb = QCheckBox("Auto Exposure")
        advanced_layout.addRow(self.auto_exposure_cb)
        tab_widget.addTab(advanced_controls_widget, "Adjustments")

        # -- ROI Controls Tab --
        roi_controls_widget = QWidget()

        roi_layout = QFormLayout(roi_controls_widget)  # Pass roi_controls_widget
        roi_layout.setSpacing(6)
        roi_layout.setContentsMargins(0, 0, 0, 0)

        self.roi_x_spin = QSpinBox()
        self.roi_x_spin.setRange(0, 8000)
        self.roi_x_spin.setSingleStep(1)
        self.roi_y_spin = QSpinBox()
        self.roi_y_spin.setRange(0, 8000)
        self.roi_y_spin.setSingleStep(1)
        self.roi_w_spin = QSpinBox()
        self.roi_w_spin.setRange(0, 8000)
        self.roi_w_spin.setSingleStep(1)
        self.roi_h_spin = QSpinBox()
        self.roi_h_spin.setRange(0, 8000)
        self.roi_h_spin.setSingleStep(1)
        self.reset_roi_btn = QPushButton("Reset ROI to Default")

        roi_layout.addRow("ROI X:", self.roi_x_spin)
        roi_layout.addRow("ROI Y:", self.roi_y_spin)
        roi_layout.addRow("ROI Width (0=full):", self.roi_w_spin)
        roi_layout.addRow("ROI Height (0=full):", self.roi_h_spin)
        roi_layout.addRow(self.reset_roi_btn)

        # self.roi_group.setLayout(roi_layout) # Set layout on the groupbox
        tab_widget.addTab(roi_controls_widget, "ROI")  # Add the groupbox to the tab

        main_layout.addWidget(
            tab_widget
        )  # Add tab widget to the main layout of the CameraControlPanel

        # Initially disable them until properties are loaded
        self.exposure_slider.setEnabled(False)
        self.gain_slider.setEnabled(False)
        self.brightness_slider.setEnabled(False)
        self.auto_exposure_cb.setEnabled(False)
        roi_controls_widget.setEnabled(
            False
        )  # Disable the whole ROI tab content initially

        # Connect signals
        # self.cam_selector.currentIndexChanged.connect(self._on_camera_selected_changed) # Already connected
        # self.res_selector.currentIndexChanged.connect(self._on_resolution_selected_changed) # Already connected

        self.exposure_slider.valueChanged.connect(self.exposure_changed)
        self.gain_slider.valueChanged.connect(self.gain_changed)
        self.brightness_slider.valueChanged.connect(self.brightness_changed)
        self.auto_exposure_cb.toggled.connect(self.auto_exposure_toggled)

        self.roi_x_spin.valueChanged.connect(self._emit_roi_change)
        self.roi_y_spin.valueChanged.connect(self._emit_roi_change)
        self.roi_w_spin.valueChanged.connect(self._emit_roi_change)
        self.roi_h_spin.valueChanged.connect(self._emit_roi_change)
        self.reset_roi_btn.clicked.connect(self.roi_reset_requested.emit)

        self.populate_camera_selector()

    def populate_camera_selector(self):
        self.cam_selector.clear()
        try:
            cams = QCameraInfo.availableCameras()
            if cams:
                for i, info in enumerate(cams):
                    self.cam_selector.addItem(
                        info.description() or f"Camera {i}",
                        {"id": i, "description": info.description() or f"Camera {i}"},
                    )
                # Try to select default, if not, select first
                default_cam_data = {
                    "id": DEFAULT_CAMERA_INDEX,
                    "description": "",
                }  # Placeholder for findData
                # This findData logic is tricky with complex dicts, simpler to iterate
                found_default = False
                for i in range(self.cam_selector.count()):
                    if self.cam_selector.itemData(i)["id"] == DEFAULT_CAMERA_INDEX:
                        self.cam_selector.setCurrentIndex(i)
                        found_default = True
                        break
                if not found_default and self.cam_selector.count() > 0:
                    self.cam_selector.setCurrentIndex(0)

                if self.cam_selector.count() > 0:
                    self._on_camera_selected_changed(
                        self.cam_selector.currentIndex()
                    )  # Emit for initial selection
                else:
                    self.cam_selector.addItem(
                        "No Qt cameras found",
                        {"id": -1, "description": "No Qt cameras found"},
                    )  # Add item before disabling
                    self.cam_selector.setEnabled(False)
            else:
                self.cam_selector.addItem(
                    "No Qt cameras found",
                    {"id": -1, "description": "No Qt cameras found"},
                )
                self.cam_selector.setEnabled(False)
        except Exception:
            log.error("Error listing Qt cameras", exc_info=True)
            self.cam_selector.addItem(
                "Error listing cameras",
                {"id": -1, "description": "Error listing cameras"},
            )
            self.cam_selector.setEnabled(False)

    def _emit_roi_change(self):
        # Only emit if the ROI group is enabled (i.e., camera is active and provides max dimensions)
        roi_tab_widget = self.findChild(QTabWidget).widget(
            2
        )  # Assuming ROI is the 3rd tab (index 2)
        if roi_tab_widget and roi_tab_widget.isEnabled():
            self.roi_changed.emit(
                self.roi_x_spin.value(),
                self.roi_y_spin.value(),
                self.roi_w_spin.value(),
                self.roi_h_spin.value(),
            )

    def _emit_reset_roi_request(self):
        # This could directly call a method on qt_cam if MainWindow passes a reference,
        # or emit a dedicated signal like `roi_reset_requested`
        # For simplicity here, we'll assume MainWindow handles the reset call via `roi_changed`
        # by MainWindow sending 0,0,0,0 (or specific default values) via a slot.
        # A more direct way is for MainWindow to have a slot that calls qt_cam.reset_roi_to_default()
        # and then qt_cam emits camera_properties_updated which includes the new ROI.
        log.info("Reset ROI button clicked - MainWindow should handle this.")
        # Let's refine this: add a signal
        # roi_reset_requested = pyqtSignal() # Add this to class signals
        # self.roi_reset_requested.emit()

    def update_control_from_properties(self, control_name, props):
        slider = None
        label = None
        checkbox = None
        is_enabled = props.get("enabled", False)  # Default to False if not specified

        if control_name == "exposure":
            slider = self.exposure_slider
            label = self.exposure_value_label
            checkbox = self.auto_exposure_cb
        elif control_name == "gain":
            slider = self.gain_slider
            label = self.gain_value_label
        elif control_name == "brightness":
            slider = self.brightness_slider
            label = self.brightness_value_label

        parent_tab_index = -1
        if control_name in ["exposure", "gain", "brightness"]:
            parent_tab_index = 1  # Adjustments tab

        tab_widget = self.findChild(QTabWidget)
        if tab_widget and parent_tab_index != -1:
            tab_widget.widget(parent_tab_index).setEnabled(
                is_enabled
            )  # Enable/disable the whole tab content

        if slider:
            slider.setEnabled(is_enabled)
            if is_enabled:
                slider.blockSignals(True)
                if "min" in props and "max" in props:
                    slider.setRange(int(props["min"]), int(props["max"]))
                if "value" in props:
                    slider.setValue(int(props["value"]))
                slider.blockSignals(False)
            if label and "value" in props:
                label.setText(f"{props['value']:.1f}")
            elif label:  # Not enabled or no value
                label.setText("N/A")
                if slider:
                    slider.setValue(0)  # Reset slider if not enabled

        if checkbox and control_name == "exposure":
            checkbox.setEnabled(is_enabled)
            if is_enabled and "is_auto_on" in props:
                checkbox.blockSignals(True)
                checkbox.setChecked(props["is_auto_on"])
                checkbox.blockSignals(False)
                if slider:  # Slider exists for exposure
                    slider.setEnabled(not props["is_auto_on"] if is_enabled else False)
            elif not is_enabled:  # if exposure control overall is disabled
                checkbox.setChecked(False)

    def update_roi_controls(self, roi_props):
        roi_tab_content_widget = self.findChild(QTabWidget).widget(
            2
        )  # Index of ROI tab

        max_w = roi_props.get("max_w", 0)
        max_h = roi_props.get("max_h", 0)
        roi_enabled = max_w > 0 and max_h > 0

        roi_tab_content_widget.setEnabled(roi_enabled)

        if roi_enabled:
            self.roi_x_spin.blockSignals(True)
            self.roi_y_spin.blockSignals(True)
            self.roi_w_spin.blockSignals(True)
            self.roi_h_spin.blockSignals(True)

            self.roi_x_spin.setRange(0, max_w - 1 if max_w > 0 else 0)
            self.roi_y_spin.setRange(0, max_h - 1 if max_h > 0 else 0)
            self.roi_w_spin.setRange(0, max_w)
            self.roi_h_spin.setRange(0, max_h)

            self.roi_x_spin.setValue(roi_props.get("x", 0))
            self.roi_y_spin.setValue(roi_props.get("y", 0))
            self.roi_w_spin.setValue(roi_props.get("w", 0))
            self.roi_h_spin.setValue(roi_props.get("h", 0))

            self.roi_x_spin.blockSignals(False)
            self.roi_y_spin.blockSignals(False)
            self.roi_w_spin.blockSignals(False)
            self.roi_h_spin.blockSignals(False)
        else:  # If ROI is disabled, reset spins to 0 or sensible defaults
            for spin in [
                self.roi_x_spin,
                self.roi_y_spin,
                self.roi_w_spin,
                self.roi_h_spin,
            ]:
                spin.blockSignals(True)
                spin.setRange(0, 0)
                spin.setValue(0)
                spin.blockSignals(False)

    def _on_camera_selected_changed(self, index):
        if index < 0:
            return  # No item selected or placeholder
        cam_data = self.cam_selector.itemData(index)
        if cam_data and cam_data["id"] != -1:
            self.camera_selected.emit(cam_data["id"], cam_data["description"])
            self.res_selector.clear()
            self.res_selector.setEnabled(
                False
            )  # Disable until new resolutions are populated
        else:  # "No camera" or error item selected
            self.camera_selected.emit(-1, "")  # Signal no active camera
            self.res_selector.clear()
            self.res_selector.setEnabled(False)
            # Also disable other controls
            self.update_control_from_properties("exposure", {"enabled": False})
            self.update_control_from_properties("gain", {"enabled": False})
            self.update_control_from_properties("brightness", {"enabled": False})
            self.update_roi_controls({"max_w": 0, "max_h": 0})

    def _on_resolution_selected_changed(self, index):
        if index < 0:
            return
        res = self.res_selector.itemData(index)
        if res:  # res should be "WIDTHxHEIGHT" string
            self.resolution_selected.emit(res)

    def update_resolutions(
        self, res_list_str
    ):  # Expects list of "WIDTHxHEIGHT" strings
        cur_text = self.res_selector.currentText()
        self.res_selector.blockSignals(True)
        self.res_selector.clear()
        if res_list_str:
            for r_str in res_list_str:
                self.res_selector.addItem(r_str, r_str)  # Store "WIDTHxHEIGHT" as data

            idx = self.res_selector.findText(cur_text)
            if idx != -1:
                self.res_selector.setCurrentIndex(idx)
            elif self.res_selector.count() > 0:
                # Try to set a default like 640x480 or the first available
                default_res_str = f"{DEFAULT_FRAME_SIZE[0]}x{DEFAULT_FRAME_SIZE[1]}"
                idx_def = self.res_selector.findText(default_res_str)
                if idx_def != -1:
                    self.res_selector.setCurrentIndex(idx_def)
                else:
                    self.res_selector.setCurrentIndex(0)
            self.res_selector.setEnabled(True)
        else:
            self.res_selector.addItem("N/A", None)
            self.res_selector.setEnabled(False)
        self.res_selector.blockSignals(False)


class PlotControlPanel(QGroupBox):
    x_axis_limits_changed = pyqtSignal(float, float)
    y_axis_limits_changed = pyqtSignal(float, float)
    export_plot_image_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Plot Controls", parent)
        layout = QFormLayout(self)
        layout.setSpacing(6)  # Reduced spacing
        layout.setContentsMargins(5, 5, 5, 5)  # Reduced margins

        self.auto_x_cb = QCheckBox("Auto-scale X")
        self.auto_x_cb.setChecked(True)
        layout.addRow(self.auto_x_cb)
        self.x_min = QDoubleSpinBox()
        self.x_max = QDoubleSpinBox()
        self.x_min.setEnabled(False)
        self.x_max.setEnabled(False)
        self.x_min.setDecimals(1)
        self.x_max.setDecimals(1)
        self.x_min.setMinimum(-1e6)
        self.x_min.setMaximum(1e6)  # Avoid very large numbers if not needed
        self.x_max.setMinimum(-1e6)
        self.x_max.setMaximum(1e6)
        x_layout = QHBoxLayout()
        x_layout.addWidget(QLabel("Min:"))
        x_layout.addWidget(self.x_min)
        x_layout.addWidget(QLabel("Max:"))
        x_layout.addWidget(self.x_max)
        layout.addRow("X-Limits:", x_layout)

        self.auto_y_cb = QCheckBox("Auto-scale Y")
        self.auto_y_cb.setChecked(False)  # Default Y to manual for consistent range
        layout.addRow(self.auto_y_cb)
        self.y_min = QDoubleSpinBox()
        self.y_max = QDoubleSpinBox()
        self.y_min.setEnabled(True)
        self.y_max.setEnabled(True)  # Enabled because auto Y is off by default
        self.y_min.setDecimals(1)
        self.y_max.setDecimals(1)
        self.y_min.setMinimum(-1e6)
        self.y_min.setMaximum(1e6)
        self.y_max.setMinimum(-1e6)
        self.y_max.setMaximum(1e6)
        self.y_min.setValue(PLOT_DEFAULT_Y_MIN)
        self.y_max.setValue(PLOT_DEFAULT_Y_MAX)
        y_layout = QHBoxLayout()
        y_layout.addWidget(QLabel("Min:"))
        y_layout.addWidget(self.y_min)
        y_layout.addWidget(QLabel("Max:"))
        y_layout.addWidget(self.y_max)
        layout.addRow("Y-Limits:", y_layout)

        self.reset_btn = QPushButton("↺ Reset Zoom/View")
        self.export_img_btn = QPushButton("Export Plot Image")
        btns_layout = QHBoxLayout()  # Use QHBoxLayout for buttons
        btns_layout.addWidget(self.reset_btn)
        btns_layout.addWidget(self.export_img_btn)
        layout.addRow(btns_layout)  # Add the QHBoxLayout to the form layout

        self.auto_x_cb.toggled.connect(
            lambda c: (self.x_min.setEnabled(not c), self.x_max.setEnabled(not c))
        )
        self.auto_y_cb.toggled.connect(
            lambda c: (self.y_min.setEnabled(not c), self.y_max.setEnabled(not c))
        )

        # Connect only if not auto
        self.x_min.valueChanged.connect(self._emit_x_if_manual)
        self.x_max.valueChanged.connect(self._emit_x_if_manual)
        self.y_min.valueChanged.connect(self._emit_y_if_manual)
        self.y_max.valueChanged.connect(self._emit_y_if_manual)

        self.export_img_btn.clicked.connect(self.export_plot_image_requested)

    def _emit_x_if_manual(self):
        if not self.auto_x_cb.isChecked():
            self.x_axis_limits_changed.emit(self.x_min.value(), self.x_max.value())

    def _emit_y_if_manual(self):
        if not self.auto_y_cb.isChecked():
            self.y_axis_limits_changed.emit(self.y_min.value(), self.y_max.value())


class TopControlPanel(QWidget):
    # Forward signals from CameraControlPanel
    camera_selected = pyqtSignal(int, str)
    resolution_selected = pyqtSignal(str)
    exposure_changed = pyqtSignal(int)
    gain_changed = pyqtSignal(int)
    brightness_changed = pyqtSignal(int)
    auto_exposure_toggled = pyqtSignal(bool)
    roi_changed = pyqtSignal(int, int, int, int)
    roi_reset_requested = pyqtSignal()

    # Forward signals from PlotControlPanel
    x_axis_limits_changed = pyqtSignal(float, float)
    y_axis_limits_changed = pyqtSignal(float, float)
    export_plot_image_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 2, 5, 2)  # Reduced top/bottom margins
        layout.setSpacing(10)  # Reduced spacing

        self.camera_controls = CameraControlPanel(self)
        # self.camera_controls.setMaximumWidth(350) # Keep this if fixed width is desired
        layout.addWidget(self.camera_controls, 1)  # Allow some stretch

        prim_box = QGroupBox("PRIM Device Status")
        prim_form = QFormLayout(prim_box)
        prim_form.setSpacing(6)
        prim_form.setContentsMargins(5, 5, 5, 5)
        self.conn_lbl = QLabel("Disconnected")
        self.conn_lbl.setStyleSheet("font-weight:bold;color:#D6C832;")  # Initial color
        prim_form.addRow("Connection:", self.conn_lbl)
        self.idx_lbl = QLabel("N/A")
        prim_form.addRow("Device Frame #:", self.idx_lbl)
        self.time_lbl = QLabel("N/A")
        prim_form.addRow("Device Time (s):", self.time_lbl)
        self.pres_lbl = QLabel("N/A")
        self.pres_lbl.setStyleSheet(
            "font-size:12pt;font-weight:bold;"
        )  # Slightly smaller font
        prim_form.addRow("Current Pressure:", self.pres_lbl)
        layout.addWidget(prim_box, 1)  # Allow some stretch

        self.plot_controls = PlotControlPanel(self)
        layout.addWidget(self.plot_controls, 1)  # Allow some stretch

        # Forward signals
        self.camera_controls.camera_selected.connect(self.camera_selected)
        self.camera_controls.resolution_selected.connect(self.resolution_selected)
        self.camera_controls.exposure_changed.connect(self.exposure_changed)
        self.camera_controls.gain_changed.connect(self.gain_changed)
        self.camera_controls.brightness_changed.connect(self.brightness_changed)
        self.camera_controls.auto_exposure_toggled.connect(self.auto_exposure_toggled)
        self.camera_controls.roi_changed.connect(self.roi_changed)
        self.camera_controls.roi_reset_requested.connect(self.roi_reset_requested)

        self.plot_controls.x_axis_limits_changed.connect(self.x_axis_limits_changed)
        self.plot_controls.y_axis_limits_changed.connect(self.y_axis_limits_changed)
        self.plot_controls.export_plot_image_requested.connect(
            self.export_plot_image_requested
        )

    def update_camera_ui_from_properties(self, properties_payload: dict):
        controls_data = properties_payload.get("controls", {})
        # Explicitly enable/disable tabs based on whether any control within them is enabled
        # This assumes a simple structure. More complex logic might be needed for fine-grained tab enabling.

        # Example: enable "Adjustments" tab if exposure, gain or brightness is enabled.
        adj_tab_enabled = any(
            props.get("enabled", False)
            for name, props in controls_data.items()
            if name in ["exposure", "gain", "brightness"]
        )
        self.camera_controls.findChild(QTabWidget).widget(1).setEnabled(adj_tab_enabled)

        for control_name, props_for_control in controls_data.items():
            self.camera_controls.update_control_from_properties(
                control_name, props_for_control
            )

        roi_data = properties_payload.get("roi", {})
        self.camera_controls.update_roi_controls(
            roi_data
        )  # This handles enabling/disabling ROI tab content

    def disable_all_camera_controls(self):
        """Call this when camera disconnects or no camera selected."""
        dummy_control_props = {
            "enabled": False,
            "value": 0,
            "min": 0,
            "max": 0,
            "is_auto_on": False,
        }
        for control in ["exposure", "gain", "brightness"]:
            self.camera_controls.update_control_from_properties(
                control, dummy_control_props
            )
        self.camera_controls.update_roi_controls(
            {"max_w": 0, "max_h": 0}
        )  # Disables ROI tab
        self.camera_controls.res_selector.clear()
        self.camera_controls.res_selector.setEnabled(False)
        self.camera_controls.findChild(QTabWidget).widget(0).setEnabled(
            True
        )  # Basic tab always enabled for cam selection
        self.camera_controls.findChild(QTabWidget).widget(1).setEnabled(
            False
        )  # Adjustments tab
        # self.camera_controls.findChild(QGroupBox,"RegionOfInterestGroup").setEnabled(False)

    def update_connection_status(self, text, connected):
        self.conn_lbl.setText(text)
        # self.conn_lbl.setProperty("connectionStatus", "connected" if connected else "disconnected")
        # self.conn_lbl.style().unpolish(self.conn_lbl); self.conn_lbl.style().polish(self.conn_lbl)
        color = (
            "#A3BE8C" if connected else ("#BF616A" if "Error" in text else "#D6C832")
        )
        self.conn_lbl.setStyleSheet(f"font-weight:bold;color:{color};")

    def update_prim_data(self, idx, t_dev, p_dev):
        self.idx_lbl.setText(str(idx))
        self.time_lbl.setText(f"{t_dev:.2f}")
        self.pres_lbl.setText(f"{p_dev:.2f} mmHg")

    def update_camera_resolutions(
        self, res_list
    ):  # res_list is list of strings "WIDTHxHEIGHT"
        self.camera_controls.update_resolutions(res_list)


class PressurePlotWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # ─── Widget setup ────────────────────────────────────────────
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # ─── Figure & axes ───────────────────────────────────────────
        # `facecolor` = the *outside* background (around the axes)
        # `tight_layout=True` auto-adjusts margins so labels don't get cut off
        self.fig = Figure(facecolor="white", tight_layout=True)  # Added tight_layout

        # create a single subplot (axes)
        self.ax = self.fig.add_subplot(111)

        # ─── Axes background ────────────────────────────────────────
        # this is the *inside* background behind your data & grid
        self.ax.set_facecolor("#FFFFFF")

        # ─── Axis labels ────────────────────────────────────────────
        # text, color, size, weight
        self.ax.set_xlabel("Time (s)", color="#000000", fontsize=16, fontweight="bold")
        self.ax.set_ylabel(
            "Pressure (mmHg)", color="#000000", fontsize=16, fontweight="bold"
        )

        # ─── Tick styling ────────────────────────────────────────────
        # controls the tick marks *and* the tick labels
        self.ax.tick_params(colors="#000000", labelsize=8)

        # ─── Spine (border) colors ───────────────────────────────────
        # you can individually style each side of the box
        for spine_pos in ["bottom", "left", "top", "right"]:
            self.ax.spines[spine_pos].set_color("#D8DEE9")

        # ─── The trace (line) ────────────────────────────────────────
        # the color= argument is what sets your data-line color
        (self.line,) = self.ax.plot([], [], "-", lw=2, color="#000000")

        self.canvas = FigureCanvas(self.fig)
        layout.addWidget(self.canvas)

        self.times, self.pressures = [], []
        self.max_pts = PLOT_MAX_POINTS
        self.manual_xlim = None
        self.manual_ylim = (PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)  # Default Y limits
        self.ax.set_ylim(self.manual_ylim)

        # Placeholder text
        self.placeholder_text_item = None
        self._show_placeholder("Waiting for PRIM device data...")

    def _show_placeholder(self, text):
        if self.placeholder_text_item:
            self.placeholder_text_item.remove()
            self.placeholder_text_item = None

        self.line.set_data([], [])  # Clear data line
        self.placeholder_text_item = self.ax.text(
            0.5,
            0.5,
            text,
            horizontalalignment="center",
            verticalalignment="center",
            transform=self.ax.transAxes,
            fontsize=12,
            color="gray",
            bbox=dict(boxstyle="round,pad=0.5", fc="#ECEFF4", ec="none", alpha=0.8),
        )
        self.canvas.draw_idle()

    def _hide_placeholder(self):
        if self.placeholder_text_item:
            self.placeholder_text_item.remove()
            self.placeholder_text_item = None
        # self.canvas.draw_idle() # No need to draw yet, update_plot will do it

    def update_plot(self, t, p, auto_x, auto_y):
        if not self.times:  # First data point
            self._hide_placeholder()

        self.times.append(t)
        self.pressures.append(p)
        if len(self.times) > self.max_pts:
            self.times = self.times[-self.max_pts :]
            self.pressures = self.pressures[-self.max_pts :]

        if not self.times:  # Should not happen if _hide_placeholder was called
            self._show_placeholder("No data received.")
            return

        self.line.set_data(self.times, self.pressures)

        current_xlim = self.ax.get_xlim()
        current_ylim = self.ax.get_ylim()

        new_xlim, new_ylim = current_xlim, current_ylim

        if auto_x:
            if len(self.times) > 1:
                rng = self.times[-1] - self.times[0]
                pad = max(1, rng * 0.05) if rng > 0 else 1.0
                new_xlim = (self.times[0] - pad * 0.1, self.times[-1] + pad * 0.9)
            elif self.times:
                new_xlim = (self.times[0] - 0.5, self.times[0] + 0.5)
            self.manual_xlim = None
        elif self.manual_xlim:
            new_xlim = self.manual_xlim

        if auto_y:
            if self.pressures:
                mn, mx = min(self.pressures), max(self.pressures)
                rng = mx - mn
                pad = (
                    rng * 0.1 if rng > 0 else (abs(mn) * 0.1 or 5.0)
                )  # Ensure pad is reasonable
                pad = max(pad, 2.0)  # Min padding
                new_ylim = (mn - pad, mx + pad)
            self.manual_ylim = None
        elif self.manual_ylim:
            new_ylim = self.manual_ylim

        if new_xlim != current_xlim:
            self.ax.set_xlim(new_xlim)
        if new_ylim != current_ylim:
            self.ax.set_ylim(new_ylim)

        self.canvas.draw_idle()

    def set_manual_x_limits(self, xmin, xmax):
        if xmin < xmax:
            self.manual_xlim = (xmin, xmax)
            self.ax.set_xlim(self.manual_xlim)
            self.canvas.draw_idle()
        else:
            log.warning("Plot: X min must be less than X max.")

    def set_manual_y_limits(self, ymin, ymax):
        if ymin < ymax:
            self.manual_ylim = (ymin, ymax)
            self.ax.set_ylim(self.manual_ylim)
            self.canvas.draw_idle()
        else:
            log.warning("Plot: Y min must be less than Y max.")

    def reset_zoom(
        self, auto_x_is_checked, auto_y_is_checked
    ):  # Receive checkbox states
        self.manual_xlim = None
        # If auto_y is not checked, reset to default manual Y, otherwise it will auto-scale.
        if not auto_y_is_checked:
            self.manual_ylim = (PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)
            self.ax.set_ylim(self.manual_ylim)
        else:  # auto_y is checked
            self.manual_ylim = None  # Allow full auto-scale

        # Force redraw with current data and new auto/manual states
        if self.times:  # If there's data, trigger a plot update
            self.update_plot(
                self.times[-1], self.pressures[-1], auto_x_is_checked, auto_y_is_checked
            )
        else:  # No data, just reset axes and show placeholder
            self.ax.set_xlim(0, 10)  # Default X for empty plot
            if not auto_y_is_checked:
                self.ax.set_ylim(self.manual_ylim)  # Apply default Y if manual
            else:
                self.ax.autoscale(enable=True, axis="y")  # Autoscale Y if checked
            self._show_placeholder("Plot cleared or waiting for data.")
        self.canvas.draw_idle()

    def clear_plot(self):
        self.times.clear()
        self.pressures.clear()
        self.line.set_data([], [])
        # self.ax.relim() # Not always reliable with draw_idle
        self.ax.set_xlim(0, 10)  # Default empty X range
        # Use the current state of the auto_y_cb to determine Y limits
        plot_controls = (
            self.parent().parent().parent().findChild(TopControlPanel).plot_controls
        )  # Bit fragile path
        is_auto_y = plot_controls.auto_y_cb.isChecked() if plot_controls else False

        if not is_auto_y:
            self.ax.set_ylim(
                self.manual_ylim
                if self.manual_ylim
                else (PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)
            )
        else:
            # If auto Y, let it adjust next time data comes or use a small default
            self.ax.set_ylim(
                PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX
            )  # Fallback if no data for auto-scale

        self._show_placeholder("Plot data cleared.")
        self.canvas.draw_idle()

    def export_as_image(self):
        if (
            not self.times and not self.placeholder_text_item
        ):  # Only warn if truly empty and no placeholder
            QMessageBox.warning(self, "Empty Plot", "Plot has no data to export.")
            return

        default_filename = f"plot_export_{time.strftime('%Y%m%d-%H%M%S')}.png"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Plot Image",
            default_filename,
            "PNG (*.png);;JPEG (*.jpg *.jpeg);;SVG (*.svg);;PDF (*.pdf)",
        )
        if path:
            try:
                # Temporarily hide placeholder if it exists for export
                placeholder_visible = False
                if (
                    self.placeholder_text_item
                    and self.placeholder_text_item.get_visible()
                ):
                    self.placeholder_text_item.set_visible(False)
                    placeholder_visible = True

                self.fig.savefig(path, dpi=300, facecolor=self.fig.get_facecolor())

                if placeholder_visible:  # Restore placeholder
                    self.placeholder_text_item.set_visible(True)

                log.info(f"Plot saved to {path}")
                status_bar_ref = (
                    self.window().statusBar() if self.window() else None
                )  # Get main window's status bar
                if status_bar_ref:
                    status_bar_ref.showMessage(
                        f"Plot exported to {os.path.basename(path)}", 3000
                    )
            except Exception as e:
                log.error("Error saving plot image", exc_info=True)
                QMessageBox.critical(
                    self, "Export Error", f"Could not save plot image: {e}"
                )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.main_content_splitter = None
        self._base_path = os.path.dirname(__file__)  # Use consistent naming
        self.icon_dir = os.path.join(self._base_path, "icons")
        self._serial_thread = None
        self.trial_recorder = None
        self._is_recording = False
        self.last_trial_basepath = None  # Initialize

        # Load icons for actions
        self.icon_record_start = QIcon(os.path.join(self.icon_dir, "record.svg"))
        self.icon_record_stop = QIcon(os.path.join(self.icon_dir, "stop.svg"))
        self.icon_recording_active = QIcon(
            os.path.join(self.icon_dir, "recording_active.svg")
        )  # Create this icon (e.g., red circle)

        self._build_console()
        self._build_central_widget_layout()  # Renamed for clarity
        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()

        self.showMaximized()
        QTimer.singleShot(300, self._adjust_splitter_sizes)  # Adjusted delay slightly
        log.info(f"{APP_NAME} started.")
        self.statusBar().showMessage("Ready. Select camera and serial port.", 5000)

        # Initial state for controls
        self.top_ctrl.update_connection_status("Disconnected", False)
        self.top_ctrl.disable_all_camera_controls()  # Ensure camera controls start disabled

        # Connect signals from TopControlPanel (which forwards from sub-panels)
        self.top_ctrl.camera_selected.connect(self._on_camera_device_selected)
        self.top_ctrl.resolution_selected.connect(self._on_camera_resolution_selected)
        self.top_ctrl.exposure_changed.connect(self._on_exposure_changed)
        self.top_ctrl.gain_changed.connect(self._on_gain_changed)
        self.top_ctrl.brightness_changed.connect(self._on_brightness_changed)
        self.top_ctrl.auto_exposure_toggled.connect(self._on_auto_exposure_toggled)
        self.top_ctrl.roi_changed.connect(self._on_roi_changed)
        self.top_ctrl.roi_reset_requested.connect(self._on_roi_reset_requested)

        self.top_ctrl.x_axis_limits_changed.connect(self.plot_w.set_manual_x_limits)
        self.top_ctrl.y_axis_limits_changed.connect(self.plot_w.set_manual_y_limits)
        self.top_ctrl.export_plot_image_requested.connect(self.plot_w.export_as_image)
        self.top_ctrl.plot_controls.reset_btn.clicked.connect(
            lambda: self.plot_w.reset_zoom(
                self.top_ctrl.plot_controls.auto_x_cb.isChecked(),
                self.top_ctrl.plot_controls.auto_y_cb.isChecked(),
            )
        )

        # Connect signals from QtCameraWidget (already done in _build_central)
        # Connect camera properties update from QtCameraWidget to TopControlPanel
        self.qt_cam.camera_properties_updated.connect(
            self.top_ctrl.update_camera_ui_from_properties
        )
        self.qt_cam.camera_resolutions_updated.connect(
            self.top_ctrl.update_camera_resolutions
        )
        self.qt_cam.camera_error.connect(self._on_camera_error)

        # Populate cameras after UI is fully up
        QTimer.singleShot(100, self.top_ctrl.camera_controls.populate_camera_selector)

    def _on_exposure_changed(self, value):
        if self.qt_cam:
            self.qt_cam.set_exposure(value)

    def _on_gain_changed(self, value):
        if self.qt_cam:
            self.qt_cam.set_gain(value)

    def _on_brightness_changed(self, value):
        if self.qt_cam:
            self.qt_cam.set_brightness(value)

    def _on_auto_exposure_toggled(self, checked):
        if self.qt_cam:
            self.qt_cam.set_auto_exposure(enable_auto=checked)

    def _on_roi_changed(self, x, y, w, h):
        if self.qt_cam:
            self.qt_cam.set_software_roi(x, y, w, h)

    def _on_roi_reset_requested(self):
        if self.qt_cam:
            self.qt_cam.reset_roi_to_default()
        # qt_cam should emit camera_properties_updated which includes new ROI values

    # Slot for camera properties from QtCameraWidget already handled by connecting to top_ctrl

    def _build_console(self):
        self.dock_console = QDockWidget("Console Log", self)
        self.dock_console.setObjectName("ConsoleLogDock")
        self.dock_console.setAllowedAreas(
            Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea
        )
        self.dock_console.setFeatures(
            QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable
        )

        console_widget = QWidget()
        console_layout = QVBoxLayout(console_widget)
        console_layout.setContentsMargins(2, 2, 2, 2)
        self.console_out = QTextEdit()
        self.console_out.setReadOnly(True)
        console_layout.addWidget(self.console_out)
        self.dock_console.setWidget(console_widget)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.dock_console)
        self.dock_console.setVisible(False)  # Start with console hidden

    def _build_central_widget_layout(self):  # Renamed
        central_widget = QWidget()
        central_widget.setObjectName("CentralWidget")

        outer_layout = QVBoxLayout(central_widget)
        outer_layout.setContentsMargins(
            2, 2, 2, 2
        )  # Reduced margins for the main content area
        outer_layout.setSpacing(3)  # Reduced spacing

        self.top_ctrl = TopControlPanel(self)
        self.top_ctrl.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed
        )  # Fixed height
        # self.top_ctrl.setMinimumHeight(100) # Adjust as needed, or let content define it
        outer_layout.addWidget(self.top_ctrl)

        self.main_content_splitter = QSplitter(Qt.Horizontal)
        self.main_content_splitter.setChildrenCollapsible(False)
        self.main_content_splitter.setStyleSheet(
            "QSplitter::handle{background-color:#D8DEE9;}"
        )  # Example color

        # Camera Pane
        # No extra container needed if QtCameraWidget handles its own background/border
        self.qt_cam = QtCameraWidget(parent=self)  # Provide parent
        # self.qt_cam.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding) # Already in QtCameraWidget
        # self.qt_cam.setMinimumSize(320, 240) # Ensure it doesn't get too small
        self.main_content_splitter.addWidget(self.qt_cam)

        # Plot Pane
        self.plot_w = PressurePlotWidget()
        # self.plot_w.setMinimumSize(320, 240)
        self.main_content_splitter.addWidget(self.plot_w)

        # Initial stretch factors - give more to video and plot
        self.main_content_splitter.setStretchFactor(0, 2)  # Camera (index 0)
        self.main_content_splitter.setStretchFactor(1, 3)  # Plot (index 1)

        outer_layout.addWidget(
            self.main_content_splitter, 1
        )  # Give splitter the stretch factor
        self.setCentralWidget(central_widget)

    @pyqtSlot(int, str)  # Explicitly define slot for camera_id, camera_description
    def _on_camera_device_selected(self, camera_id: int, camera_description: str):
        log.info(f"Camera selected: ID={camera_id}, Desc='{camera_description}'")
        if self.qt_cam:
            if camera_id == -1:  # "No camera" or error item
                self.qt_cam.set_active_camera(-1, "")  # Disconnect camera
                self.top_ctrl.disable_all_camera_controls()
                self.top_ctrl.update_camera_resolutions([])  # Clear resolutions
            else:
                self.qt_cam.set_active_camera(camera_id, camera_description)
        else:
            log.error("qt_cam widget not initialized when selecting camera.")
            self.top_ctrl.disable_all_camera_controls()

    @pyqtSlot(str)  # Explicitly define slot for resolution string
    def _on_camera_resolution_selected(
        self, resolution_str: str
    ):  # resolution_str is "WIDTHxHEIGHT"
        log.info(f"Camera resolution selected: {resolution_str}")
        if not self.qt_cam:
            log.error("qt_cam widget not initialized for resolution change.")
            return
        if not resolution_str or "x" not in resolution_str:
            log.warning(f"Invalid resolution string format: {resolution_str}")
            return
        try:
            w_str, h_str = resolution_str.split("x")
            w, h = int(w_str), int(h_str)
            self.qt_cam.set_active_resolution(w, h)
        except ValueError as e:
            log.error(f"Invalid resolution string values: {resolution_str} - {e}")

    @pyqtSlot(QImage, object)  # QImage for display, object for BGR frame
    def _on_frame_ready(self, qimage, bgr_frame_obj):
        if self._is_recording and self.trial_recorder and bgr_frame_obj is not None:
            try:
                self.trial_recorder.write_video_frame(bgr_frame_obj)
            except Exception as e:
                log.error(f"Error writing video frame: {e}", exc_info=True)
                self._stop_pc_recording()  # Stop on error
                self.statusBar().showMessage(
                    "ERROR: Video recording failed critically.", 5000
                )

    @pyqtSlot(str, int)  # error_message, error_code
    def _on_camera_error(self, error_message: str, error_code: int):
        log.error(f"Camera Error in MainWindow: {error_message} (Code: {error_code})")
        # Display in status bar or a non-modal notification if preferred over QMessageBox
        self.statusBar().showMessage(f"Camera Error: {error_message}", 5000)
        # Potentially disable camera-dependent UI elements
        self.top_ctrl.disable_all_camera_controls()
        self.start_trial_action.setEnabled(False)  # Can't record if camera error

    def _build_menu(self):
        mb = self.menuBar()
        file_menu = mb.addMenu("&File")
        exp_data = QAction(
            QIcon(os.path.join(self.icon_dir, "csv.svg")), "Export Plot &Data…", self
        )
        exp_data.triggered.connect(self._on_export_plot_data_csv)
        file_menu.addAction(exp_data)

        exp_img = QAction(
            QIcon(os.path.join(self.icon_dir, "image.svg")), "Export Plot &Image…", self
        )
        exp_img.triggered.connect(self.plot_w.export_as_image)  # Direct connect
        file_menu.addAction(exp_img)

        file_menu.addSeparator()
        exit_act = QAction(
            QIcon(os.path.join(self.icon_dir, "exit.svg")), "&Exit", self
        )
        exit_act.setShortcut(QKeySequence.Quit)  # Standard shortcut
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)

        acq_menu = mb.addMenu("&Acquisition")
        self.start_trial_action = QAction(
            self.icon_record_start, "Start PC Recording", self
        )
        self.start_trial_action.setShortcut(Qt.CTRL | Qt.Key_R)
        self.start_trial_action.triggered.connect(self._start_pc_recording)
        self.start_trial_action.setEnabled(False)  # Disabled until connected
        acq_menu.addAction(self.start_trial_action)

        self.stop_trial_action = QAction(
            self.icon_record_stop, "Stop PC Recording", self
        )
        self.stop_trial_action.setShortcut(Qt.CTRL | Qt.Key_T)
        self.stop_trial_action.triggered.connect(self._stop_pc_recording)
        self.stop_trial_action.setEnabled(False)
        acq_menu.addAction(self.stop_trial_action)

        view_menu = mb.addMenu("&View")
        toggle_console_act = self.dock_console.toggleViewAction()
        toggle_console_act.setText("Toggle Console Log")
        toggle_console_act.setIcon(QIcon(os.path.join(self.icon_dir, "console.svg")))
        view_menu.addAction(toggle_console_act)
        # Add "Focus Mode" action here later

        plot_menu = mb.addMenu("&Plot")
        self.clear_plot_action = QAction(
            QIcon(os.path.join(self.icon_dir, "clear_plot.svg")),
            "Clear Plot Data",
            self,
        )
        self.clear_plot_action.triggered.connect(self._on_clear_plot)
        plot_menu.addAction(self.clear_plot_action)

        reset_zoom_act = QAction(
            QIcon(os.path.join(self.icon_dir, "reset_zoom.svg")),
            "Reset Zoom/View",
            self,
        )
        reset_zoom_act.triggered.connect(
            self.top_ctrl.plot_controls.reset_btn.click
        )  # Trigger button click
        plot_menu.addAction(reset_zoom_act)

        help_menu = mb.addMenu("&Help")
        about_act = QAction(
            QIcon(os.path.join(self.icon_dir, "about.svg")), "&About", self
        )
        about_act.triggered.connect(self._on_about)
        help_menu.addAction(about_act)

        qt_act = QAction("About &Qt", self)  # No icon needed for this standard item
        qt_act.triggered.connect(QApplication.instance().aboutQt)
        help_menu.addAction(qt_act)

    def _build_toolbar(self):
        tb = QToolBar("Main Controls")
        tb.setObjectName("MainToolBar")
        tb.setIconSize(QSize(20, 20))  # Slightly smaller icons
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(Qt.TopToolBarArea, tb)

        self.act_connect = QAction(
            QIcon(os.path.join(self.icon_dir, "plug.svg")), "&Connect", self
        )
        self.act_connect.setToolTip("Connect to PRIM device")
        self.act_connect.triggered.connect(self._toggle_serial)
        tb.addAction(self.act_connect)

        self.port_combo = QComboBox()
        self.port_combo.setToolTip("Select Serial Port")
        self.port_combo.setMinimumWidth(180)  # Adjust as needed
        self.port_combo.addItem("🔌 Simulated Data", None)  # Use an icon/emoji
        try:
            ports = list_serial_ports()
            if ports:
                for p_dev, p_desc in ports:
                    self.port_combo.addItem(
                        f"{p_dev} ({p_desc or 'Serial Port'})", p_dev
                    )
            else:
                self.port_combo.addItem(
                    "No serial ports found", "NO_PORTS_FOUND_PLACEHOLDER"
                )
        except Exception as e:
            log.error("Error listing serial ports for toolbar", exc_info=True)
            self.port_combo.addItem("Error listing ports", "ERROR_PORTS_PLACEHOLDER")
        tb.addWidget(self.port_combo)

        tb.addSeparator()
        tb.addAction(self.start_trial_action)
        tb.addAction(self.stop_trial_action)
        tb.addSeparator()
        tb.addAction(self.clear_plot_action)  # Re-use action from menu

        self.open_last_trial_folder_action = QAction(
            QIcon(os.path.join(self.icon_dir, "folder_open.svg")),
            "Open Last Trial Folder",
            self,
        )
        self.open_last_trial_folder_action.triggered.connect(
            self._open_last_trial_folder
        )
        self.open_last_trial_folder_action.setEnabled(False)
        tb.addAction(self.open_last_trial_folder_action)

    def _build_statusbar(self):
        sb = self.statusBar() or QStatusBar(self)
        self.setStatusBar(sb)  # Ensure status bar exists
        self.app_time_lbl = QLabel("App Time: 00:00:00")
        sb.addPermanentWidget(self.app_time_lbl)

        self._app_elapsed_seconds = 0
        self._app_timer = QTimer(self)  # Store timer to prevent garbage collection
        self._app_timer.setInterval(1000)
        self._app_timer.timeout.connect(self._tick_app_elapsed_time)
        self._app_timer.start()

    def _adjust_splitter_sizes(self):  # Renamed
        try:
            if self.main_content_splitter and self.main_content_splitter.isVisible():
                total_width = self.main_content_splitter.width()
                if total_width > 100:  # Ensure splitter has a valid width
                    # Use stretch factors to guide, then can fine-tune if needed
                    # The setStretchFactor calls already guide the initial distribution.
                    # If explicit sizes are needed:
                    # sizes = [total_width * 0.4, total_width * 0.6] # Example: 40% camera, 60% plot
                    # self.main_content_splitter.setSizes(list(map(int, sizes)))
                    pass  # Stretch factors should handle it now.
                else:
                    log.debug(
                        f"Splitter width too small ({total_width}) for adjustment. Retrying later or check visibility."
                    )
                    # QTimer.singleShot(500, self._adjust_splitter_sizes) # Optional: retry if needed
            else:
                log.warning("Splitter not found or not visible for size adjustment.")
        except Exception as e:
            log.warning(f"Could not adjust splitter sizes: {e}")

    def _toggle_serial(self):
        sb = self.statusBar()
        if not self._serial_thread or not self._serial_thread.isRunning():
            port_data = self.port_combo.currentData()
            if (
                port_data == "NO_PORTS_FOUND_PLACEHOLDER"
                or port_data == "ERROR_PORTS_PLACEHOLDER"
            ):
                QMessageBox.warning(
                    self,
                    "Serial Port Issue",
                    "Cannot connect: No valid serial port selected or available.",
                )
                return

            port = port_data  # This is `None` for simulated, or the port string

            try:
                self._serial_thread = SerialThread(
                    port=port, parent=self
                )  # Pass parent
                self._serial_thread.data_ready.connect(self._on_serial_data_ready)
                self._serial_thread.error_occurred.connect(self._on_serial_error)
                self._serial_thread.status_changed.connect(self._on_serial_status)
                self._serial_thread.finished.connect(
                    self._on_serial_thread_finished
                )  # Important for cleanup
                self._serial_thread.start()
                # Status update will be handled by _on_serial_status
            except Exception as e_thread_start:
                log.error("Failed to start SerialThread", exc_info=True)
                QMessageBox.critical(
                    self,
                    "Serial Error",
                    f"Could not start serial thread: {e_thread_start}",
                )
                self._serial_thread = None  # Ensure it's None
                self.top_ctrl.update_connection_status("Error", False)
                # Ensure actions are correctly enabled/disabled
                self.act_connect.setIcon(QIcon(os.path.join(self.icon_dir, "plug.svg")))
                self.act_connect.setText("&Connect")
                self.start_trial_action.setEnabled(False)
                self.port_combo.setEnabled(True)
        else:  # Thread is running, so stop it
            if self._serial_thread:
                self._serial_thread.stop()
            # Status update will be handled by _on_serial_thread_finished via _on_serial_status("Disconnected")

    def _on_serial_status(self, msg: str):
        self.statusBar().showMessage(f"PRIM: {msg}", 4000)
        log.info(f"Serial Status: {msg}")

        is_connected_or_simulating = (
            "connected" in msg.lower() or "simulation mode" in msg.lower()
        )
        is_error = "error" in msg.lower()

        current_status_text = msg
        if is_error:
            current_status_text = (
                f"Error: {msg.split(':')[-1].strip()[:30]}..."
                if ":" in msg
                else msg[:30] + "..."
            )

        self.top_ctrl.update_connection_status(
            current_status_text, is_connected_or_simulating and not is_error
        )

        if is_connected_or_simulating and not is_error:
            self.act_connect.setIcon(
                QIcon(os.path.join(self.icon_dir, "plug-disconnect.svg"))
            )
            self.act_connect.setText("&Disconnect PRIM")
            self.start_trial_action.setEnabled(True)  # Enable recording if connected
            self.port_combo.setEnabled(False)
            self.plot_w._hide_placeholder()  # Hide placeholder when connection is active
            self.plot_w.clear_plot()  # Clear plot on new connection
        else:  # Disconnected or error
            self.act_connect.setIcon(QIcon(os.path.join(self.icon_dir, "plug.svg")))
            self.act_connect.setText("&Connect to PRIM")
            if self._is_recording:  # If was recording and serial disconnected
                self._stop_pc_recording()
                QMessageBox.warning(
                    self,
                    "Recording Stopped",
                    "Serial connection lost. PC recording has been stopped.",
                )
            self.start_trial_action.setEnabled(False)
            self.port_combo.setEnabled(True)
            self.plot_w._show_placeholder(
                "PRIM device disconnected. Connect to view data."
            )

    def _on_serial_error(self, error_message: str):
        log.error(f"Serial Thread Error Reported: {error_message}")
        # QMessageBox.warning(self, "PRIM Device Error", error_message) # Can be noisy
        self.statusBar().showMessage(f"PRIM Error: {error_message}", 5000)
        # Update status will be handled by _on_serial_status if it emits a disconnected/error state
        # Ensure UI reflects error state properly
        self.top_ctrl.update_connection_status(f"Error: {error_message[:30]}...", False)
        self.act_connect.setIcon(QIcon(os.path.join(self.icon_dir, "plug.svg")))
        self.act_connect.setText("&Connect to PRIM")
        if self._is_recording:
            self._stop_pc_recording()
        self.start_trial_action.setEnabled(False)
        self.port_combo.setEnabled(True)

    def _on_serial_thread_finished(self):
        log.info("Serial thread has finished.")
        self._serial_thread = None  # Crucial for allowing reconnection
        # Call _on_serial_status to ensure UI is updated to disconnected state
        # unless an error message already set it appropriately.
        # Check current status to avoid overriding specific error messages.
        if "Error" not in self.top_ctrl.conn_lbl.text():
            self._on_serial_status("Disconnected")

    def _start_pc_recording(self):
        if not (self._serial_thread and self._serial_thread.isRunning()):
            QMessageBox.warning(
                self,
                "Not Connected",
                "PRIM device not connected or simulating. Cannot start PC recording.",
            )
            return
        if not self.qt_cam or not self.qt_cam.cap or not self.qt_cam.cap.isOpened():
            if self.qt_cam.camera_id == -1:  # No camera explicitly selected
                QMessageBox.warning(
                    self,
                    "No Camera Selected",
                    "Please select a camera device to start recording.",
                )
            else:  # Camera selected but failed to open
                QMessageBox.warning(
                    self,
                    "Camera Not Ready",
                    "Camera is not active or failed to open. Cannot start recording.",
                )
            return

        # Trial Info Dialog
        dlg = QDialog(self)
        dlg.setWindowTitle("Start New PC Recording Trial")
        form = QFormLayout(dlg)
        self.trial_name_edit = QLineEdit(
            f"Trial_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}"
        )
        form.addRow("Trial Name/ID:", self.trial_name_edit)
        self.operator_edit = QLineEdit()
        form.addRow("Operator:", self.operator_edit)
        self.sample_edit = QLineEdit()
        form.addRow("Sample Details:", self.sample_edit)
        self.notes_edit = QTextEdit()
        self.notes_edit.setFixedHeight(70)  # Compacted
        form.addRow("Notes:", self.notes_edit)
        # ── Add an Output Format combo-box here ────────────────────────────
        self.format_selector = QComboBox()
        self.format_selector.addItems(["AVI", "TIFF stack"])
        form.addRow("Output Format:", self.format_selector)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)

        if dlg.exec_() != QDialog.Accepted:
            return

        trial_name = (
            self.trial_name_edit.text()
            or f"Trial_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}"
        )
        operator = self.operator_edit.text()
        sample = self.sample_edit.text()
        notes = self.notes_edit.toPlainText()

        # Path setup
        base_dir = PRIM_RESULTS_DIR
        folder_name_safe = (
            "".join(
                c if c.isalnum() or c in (" ", "_", "-") else "_" for c in trial_name
            )
            .rstrip()
            .replace(" ", "_")
        )
        trial_folder = os.path.join(base_dir, folder_name_safe)
        try:
            os.makedirs(trial_folder, exist_ok=True)
        except OSError as e_mkdir:
            log.error(f"Failed to create trial directory {trial_folder}: {e_mkdir}")
            QMessageBox.critical(
                self,
                "Directory Error",
                f"Could not create trial directory:\n{trial_folder}\n{e_mkdir}",
            )
            return

        base_save_path = os.path.join(trial_folder, folder_name_safe)  # Filename base

        # ── Read the user’s choice & map to extension ─────────────────────
        fmt = self.format_selector.currentText()
        video_ext = "avi" if fmt == "AVI" else "tiff"
        # ───────────────────────────────────────────────────────────────────

        try:
            fw, fh = DEFAULT_FRAME_SIZE  # Fallback
            if self.qt_cam and hasattr(
                self.qt_cam, "get_current_resolution"
            ):  # Check attribute first
                current_cam_res = self.qt_cam.get_current_resolution()  # This is QSize
                if (
                    current_cam_res
                    and not current_cam_res.isEmpty()
                    and current_cam_res.width() > 0
                    and current_cam_res.height() > 0
                ):
                    fw, fh = current_cam_res.width(), current_cam_res.height()
                else:
                    log.warning(
                        f"Could not get valid resolution from camera, falling back to default {fw}x{fh}"
                    )
            else:
                log.warning(
                    f"qt_cam or get_current_resolution not available, falling back to default {fw}x{fh}"
                )

            log.info(
                f"Starting trial recording. Video frame size: {fw}x{fh}. Target FPS: {DEFAULT_FPS}"
            )
            self.trial_recorder = TrialRecorder(
                base_save_path,
                fps=DEFAULT_FPS,
                frame_size=(fw, fh),
                video_codec=self.qt_cam.camera_description,  # e.g. "DMK 33UX250"
                video_ext=DEFAULT_VIDEO_EXTENSION,
            )
            if (
                not self.trial_recorder or not self.trial_recorder.is_recording
            ):  # is_recording checks if internal recorders initialized
                raise RuntimeError(
                    "TrialRecorder failed to initialize one or more internal recorders (video/CSV). Check logs."
                )

            self.last_trial_basepath = trial_folder  # Store the folder path
            self.open_last_trial_folder_action.setEnabled(True)

            # Metadata
            meta_filepath = f"{base_save_path}_metadata.txt"
            with open(meta_filepath, "w") as mf:
                mf.write(
                    f"Trial Name: {trial_name}\n"
                    f"Date: {QDateTime.currentDateTime().toString('yyyy-MM-dd HH:mm:ss')}\n"
                    f"Operator: {operator}\n"
                    f"Sample Details: {sample}\n"
                    f"FPS Target (Video): {DEFAULT_FPS}\n"
                    f"Resolution (Video): {fw}x{fh}\n"
                    f"Video File: {os.path.basename(self.trial_recorder.video.filename) if self.trial_recorder.video else 'N/A'}\n"
                    f"CSV File: {os.path.basename(self.trial_recorder.csv.filename) if self.trial_recorder.csv else 'N/A'}\n"
                    f"Notes:\n{notes}\n"
                )
            log.info(f"Metadata saved to {meta_filepath}")

            self._is_recording = True
            self.start_trial_action.setEnabled(False)
            self.start_trial_action.setIcon(self.icon_recording_active)  # Change icon
            self.stop_trial_action.setEnabled(True)
            self.plot_w.clear_plot()  # Clear plot for new recording
            self.statusBar().showMessage(
                f"PC Recording Started: {trial_name}", 0
            )  # Persistent message
            log.info(f"PC recording started. Base path: {base_save_path}")

        except Exception as e_rec_start:
            log.error("Failed to start PC recording process", exc_info=True)
            QMessageBox.critical(
                self, "Recording Error", f"Could not start recording: {e_rec_start}"
            )
            if self.trial_recorder:
                self.trial_recorder.stop()  # Cleanup
            self.trial_recorder = None
            self._is_recording = False
            self.open_last_trial_folder_action.setEnabled(
                bool(self.last_trial_basepath)
            )  # Only if a path was set
            self.start_trial_action.setIcon(self.icon_record_start)  # Reset icon
            self.start_trial_action.setEnabled(
                self._serial_thread is not None and self._serial_thread.isRunning()
            )  # Re-evaluate
            self.stop_trial_action.setEnabled(False)

    def _stop_pc_recording(self):
        if self.trial_recorder:
            base = (
                os.path.basename(self.trial_recorder.basepath_with_ts)
                if hasattr(self.trial_recorder, "basepath_with_ts")
                else "UnknownTrial"
            )
            try:
                frames_recorded = self.trial_recorder.video_frame_count
            except AttributeError:
                frames_recorded = "N/A"

            self.trial_recorder.stop()  # This handles closing files
            log.info(
                f"PC recording stopped for {base}. Video frames recorded: {frames_recorded}"
            )
            self.statusBar().showMessage(
                f"PC Recording Stopped: {base}. Frames: {frames_recorded}", 5000
            )
            self.trial_recorder = None
        else:
            log.info("Stop recording called but no trial recorder active.")
            self.statusBar().showMessage("PC Recording Stopped.", 3000)

        self._is_recording = False
        self.start_trial_action.setIcon(self.icon_record_start)  # Reset icon
        is_serial_connected = (
            self._serial_thread is not None and self._serial_thread.isRunning()
        )
        is_camera_ready = (
            self.qt_cam is not None
            and self.qt_cam.cap is not None
            and self.qt_cam.cap.isOpened()
        )
        self.start_trial_action.setEnabled(is_serial_connected and is_camera_ready)
        self.stop_trial_action.setEnabled(False)
        self.open_last_trial_folder_action.setEnabled(bool(self.last_trial_basepath))

    @pyqtSlot(int, float, float)  # idx, t_dev, p_dev
    def _on_serial_data_ready(self, idx, t_dev, p_dev):
        self.top_ctrl.update_prim_data(idx, t_dev, p_dev)

        auto_x = self.top_ctrl.plot_controls.auto_x_cb.isChecked()
        auto_y = self.top_ctrl.plot_controls.auto_y_cb.isChecked()
        self.plot_w.update_plot(t_dev, p_dev, auto_x, auto_y)

        if (
            self.dock_console.isVisible() and self.console_out
        ):  # Only process if console is visible
            line = f"Data: Idx={idx}, Time={t_dev:.3f}s, Pressure={p_dev:.2f} mmHg"
            self.console_out.append(
                line
            )  # append() is efficient enough for moderate rates
            # Auto-scrolling is usually default for QTextEdit with append
            # Limit console lines for performance if rate is very high (already implemented)
            # doc = self.console_out.document()
            # if doc and doc.blockCount() > 500: # Using blockCount is more accurate
            #     cursor = self.console_out.textCursor()
            #     cursor.movePosition(QTextCursor.Start)
            #     cursor.movePosition(QTextCursor.NextBlock, QTextCursor.KeepAnchor, doc.blockCount() - 200)
            #     cursor.removeSelectedText()
            #     cursor.movePosition(QTextCursor.End)
            #     self.console_out.setTextCursor(cursor)

        if self._is_recording and self.trial_recorder:
            try:
                self.trial_recorder.write_csv_data(t_dev, idx, p_dev)
            except Exception as e_csv:
                log.error("Error writing CSV data during recording", exc_info=True)
                self._stop_pc_recording()  # Stop trial
                self.statusBar().showMessage(
                    "ERROR: CSV data recording failed critically.", 5000
                )

    def _tick_app_elapsed_time(self):
        self._app_elapsed_seconds += 1
        h = self._app_elapsed_seconds // 3600
        m = (self._app_elapsed_seconds % 3600) // 60
        s = self._app_elapsed_seconds % 60
        self.app_time_lbl.setText(
            f"Session: {h:02}:{m:02}:{s:02}"
        )  # "Session" sounds better

    def _on_clear_plot(self):
        self.plot_w.clear_plot()
        self.statusBar().showMessage("Plot data cleared.", 3000)

    def _on_export_plot_data_csv(self):
        if not self.plot_w.times:  # Check if plot has actual data
            QMessageBox.information(self, "No Data", "No data in plot to export.")
            return

        default_filename = (
            f"plot_data_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}.csv"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Plot Data As CSV…", default_filename, "CSV Files (*.csv)"
        )
        if not path:
            return

        try:
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["time_s", "pressure_mmHg"])  # Header
                for t, p in zip(self.plot_w.times, self.plot_w.pressures):
                    writer.writerow([f"{t:.3f}", f"{p:.2f}"])
            self.statusBar().showMessage(
                f"Plot data exported to {os.path.basename(path)}", 3000
            )
            log.info(f"Plot data exported to {path}")
        except Exception as e_export:
            log.error("Error exporting plot data to CSV", exc_info=True)
            QMessageBox.critical(
                self, "Export Error", f"Could not export plot data: {e_export}"
            )

    def _open_last_trial_folder(self):
        if self.last_trial_basepath and os.path.isdir(self.last_trial_basepath):
            try:
                QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_trial_basepath))
                log.info(f"Opened last trial folder: {self.last_trial_basepath}")
            except Exception as e_open_folder:  # Catch any exception during openUrl
                log.error(
                    f"Failed to open folder {self.last_trial_basepath}: {e_open_folder}"
                )
                QMessageBox.warning(
                    self, "Open Folder Error", f"Could not open folder: {e_open_folder}"
                )
        else:
            QMessageBox.information(
                self,
                "No Folder",
                "No previous trial folder recorded or path is invalid.",
            )
            log.warning(
                f"Could not open last trial folder. Path: {self.last_trial_basepath}"
            )

    def _on_about(self):
        QMessageBox.about(self, f"About {APP_NAME}", ABOUT_TEXT)

    def closeEvent(self, ev):
        log.info("Application close event triggered.")
        if self._is_recording:
            reply = QMessageBox.question(
                self,
                "Confirm Exit",
                "A trial is currently recording. Are you sure you want to exit? This will stop the recording.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                ev.ignore()
                return
            else:
                self._stop_pc_recording()  # Gracefully stop recording

        if self._serial_thread and self._serial_thread.isRunning():
            log.info("Stopping serial thread before exit...")
            self._serial_thread.stop()
            if not self._serial_thread.wait(2000):  # Wait up to 2s
                log.warning(
                    "Serial thread did not stop gracefully on exit. May need to terminate."
                )
                self._serial_thread.terminate()  # Force if necessary

        if self.qt_cam:
            self.qt_cam.close()  # Ensure camera resources are released

        log.info(f"{APP_NAME} is closing.")
        super().closeEvent(ev)
