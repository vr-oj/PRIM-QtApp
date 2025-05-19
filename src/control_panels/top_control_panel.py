import logging

from PyQt5.QtWidgets import (
    QWidget,
    QGroupBox,
    QTabWidget,  # Keep this if used, though not directly in this snippet
    QFormLayout,
    QHBoxLayout,
    QLabel,
)
from PyQt5.QtCore import (
    pyqtSignal,
    QObject,
)  # Import QObject if not already for type hinting

# Assuming CameraControlPanel and PlotControlPanel are in the same directory
# or Python's import system can find them.
from .camera_control_panel import CameraControlPanel
from .plot_control_panel import PlotControlPanel

# Conditional import for ic4.DeviceInfo type hint
try:
    import imagingcontrol4 as ic4

    # This is primarily for type hinting if DeviceInfo is passed through signals
except ImportError:
    ic4 = None  # Define ic4 as None if library is not available

log = logging.getLogger(__name__)


class TopControlPanel(QWidget):
    # This signal will now emit an object (ic4.DeviceInfo or None)
    camera_selected = pyqtSignal(object)  # CHANGED SIGNATURE HERE

    resolution_selected = pyqtSignal(str)
    exposure_changed = pyqtSignal(int)
    gain_changed = pyqtSignal(float)  # Changed to float to match CameraControlPanel
    # brightness_changed = pyqtSignal(int) # Commented out as it's not used with TIS cams
    auto_exposure_toggled = pyqtSignal(bool)
    roi_changed = pyqtSignal(int, int, int, int)
    roi_reset_requested = pyqtSignal()

    # Signals from PlotControlPanel (forwarded)
    x_axis_limits_changed = pyqtSignal(float, float)
    y_axis_limits_changed = pyqtSignal(float, float)
    export_plot_image_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 2, 5, 2)  # Reduced top/bottom margins slightly
        layout.setSpacing(10)

        # Camera Controls Section
        # GroupBox for camera controls is within CameraControlPanel itself
        self.camera_controls = CameraControlPanel(self)
        layout.addWidget(self.camera_controls, 1)  # Stretch factor 1

        # PRIM Device Status Section
        status_box = QGroupBox("PRIM Device Status")
        status_layout = QFormLayout(status_box)
        self.conn_lbl = QLabel("Disconnected")
        self.conn_lbl.setStyleSheet(
            "font-weight:bold;color:#D6C832;"
        )  # Yellowish for disconnected
        status_layout.addRow("Connection:", self.conn_lbl)

        self.idx_lbl = QLabel("N/A")
        status_layout.addRow("Device Frame #:", self.idx_lbl)

        self.time_lbl = QLabel("N/A")
        status_layout.addRow("Device Time (s):", self.time_lbl)

        self.pres_lbl = QLabel("N/A")
        self.pres_lbl.setStyleSheet(
            "font-size:12pt;font-weight:bold;"
        )  # Make pressure stand out
        status_layout.addRow("Current Pressure:", self.pres_lbl)
        layout.addWidget(status_box, 1)  # Stretch factor 1

        # Plot Controls Section
        # GroupBox for plot controls is within PlotControlPanel itself
        self.plot_controls = PlotControlPanel(self)
        layout.addWidget(self.plot_controls, 1)  # Stretch factor 1

        # Forward camera signals
        cc = self.camera_controls
        cc.camera_selected.connect(
            self.camera_selected
        )  # Now compatible (object -> object)
        cc.resolution_selected.connect(self.resolution_selected)
        cc.exposure_changed.connect(self.exposure_changed)
        cc.gain_changed.connect(
            self.gain_changed
        )  # Ensure this matches (float -> float)
        # cc.brightness_changed.connect(self.brightness_changed) # Still commented
        cc.auto_exposure_toggled.connect(self.auto_exposure_toggled)
        cc.roi_changed.connect(self.roi_changed)
        cc.roi_reset_requested.connect(self.roi_reset_requested)

        # Forward plot signals
        pc = self.plot_controls
        pc.x_axis_limits_changed.connect(self.x_axis_limits_changed)
        pc.y_axis_limits_changed.connect(self.y_axis_limits_changed)
        pc.export_plot_image_requested.connect(self.export_plot_image_requested)
        # Note: The reset_btn in PlotControlPanel has its own direct connection logic
        # or can emit a signal if preferred. If it emits a signal like `reset_plot_view_requested`,
        # you would connect it here:
        # pc.reset_plot_view_requested.connect(self.reset_plot_view_requested)

    @pyqtSlot(dict)  # Slot to receive properties from QtCameraWidget via MainWindow
    def update_camera_ui_from_properties(self, props: dict):
        # This method is now primarily for enabling/disabling tabs if needed,
        # as the detailed UI updates happen within CameraControlPanel.
        log.debug(f"TopControlPanel received camera properties: {props}")
        # Pass properties directly to the CameraControlPanel instance
        self.camera_controls.update_camera_properties_ui(props)

    def disable_all_camera_controls(self):
        # This method can now just call the more detailed one in CameraControlPanel
        self.camera_controls.disable_all_controls()
        # You might also want to clear resolution list here if it's managed by TopControlPanel
        # However, CameraControlPanel's disable_all_controls already handles its res_selector.

    def update_connection_status(self, text: str, connected: bool):
        self.conn_lbl.setText(text)
        if connected:
            color = "#A3BE8C"  # Greenish for connected
        elif "error" in text.lower() or "failed" in text.lower():
            color = "#BF616A"  # Reddish for error
        else:
            color = "#D6C832"  # Yellowish for disconnected/pending
        self.conn_lbl.setStyleSheet(f"font-weight:bold;color:{color};")

    def update_prim_data(self, idx: int, t_dev: float, p_dev: float):
        self.idx_lbl.setText(str(idx))
        self.time_lbl.setText(f"{t_dev:.2f}")  # Consistent formatting
        self.pres_lbl.setText(f"{p_dev:.2f} mmHg")

    @pyqtSlot(
        list
    )  # Slot to receive resolution list from QtCameraWidget via MainWindow
    def update_camera_resolutions(self, modes: list):
        # Pass this directly to the CameraControlPanel instance
        self.camera_controls.update_camera_resolutions_list(modes)
