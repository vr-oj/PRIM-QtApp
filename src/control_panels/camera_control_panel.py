import logging
from PyQt5.QtWidgets import (
    QGroupBox,
    QWidget,
    QTabWidget,
    QFormLayout,
    QScrollArea,
    QLabel,
    QComboBox,
    QDoubleSpinBox,
    QCheckBox,
    QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal

log = logging.getLogger(__name__)

# Try to import the IC4 library for camera enumeration
try:
    import imagingcontrol4 as ic4
except ImportError:
    ic4 = None


class CameraControlPanel(QGroupBox):
    """
    Control panel for camera settings: device selection, resolution, exposure, and gain.
    """

    # Emitted when any camera parameter changes (param_name, value)
    parameter_changed = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__("Camera Controls", parent)
        layout = QFormLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self.tabs = QTabWidget()
        layout.addRow(self.tabs)

        # -- Source Tab --
        src_tab = QWidget()
        src_layout = QFormLayout(src_tab)

        # Camera device selector
        self.cam_selector = QComboBox()
        self.cam_selector.addItem("Select Camera", None)
        self.cam_selector.setToolTip("Select Camera Device")
        src_layout.addRow("Device:", self.cam_selector)

        # Resolution selector
        self.res_selector = QComboBox()
        self.res_selector.setToolTip("Select Resolution and Format")
        src_layout.addRow("Resolution:", self.res_selector)

        # Display for current resolution
        self.current_res_label = QLabel("––")
        src_layout.addRow("Current:", self.current_res_label)

        self.tabs.addTab(src_tab, "Source")

        # -- Adjustments Tab --
        adj_tab = QWidget()
        adj_layout = QFormLayout(adj_tab)

        # Exposure control
        self.exposure_box = QDoubleSpinBox()
        self.exposure_box.setDecimals(1)
        self.exposure_box.setSuffix(" ms")
        self.exposure_box.setRange(0.1, 10000.0)
        self.exposure_box.setKeyboardTracking(False)
        adj_layout.addRow("Exposure:", self.exposure_box)

        # Auto exposure checkbox
        self.auto_exposure_cb = QCheckBox("Auto Exposure")
        adj_layout.addRow(self.auto_exposure_cb)

        # Gain control
        self.gain_box = QDoubleSpinBox()
        self.gain_box.setDecimals(1)
        self.gain_box.setKeyboardTracking(False)
        adj_layout.addRow("Gain (dB):", self.gain_box)

        self.tabs.addTab(adj_tab, "Adjustments")
        # Initially disable adjustments until a camera is selected
        adj_tab.setEnabled(False)

        # Connect UI signals to emit parameter changes
        # DEBUG: log any raw combobox index change
        self.cam_selector.currentIndexChanged.connect(
            lambda idx: log.info(
                f"[DEBUG] CameraControlPanel.cam_selector idx={idx}, data={self.cam_selector.itemData(idx)}"
            )
        )
        # then emit the parameter_changed signal
        self.cam_selector.currentIndexChanged.connect(
            lambda idx: self.parameter_changed.emit(
                "CameraSelection", self.cam_selector.itemData(idx)
            )
        )
        self.res_selector.currentIndexChanged.connect(
            lambda idx: self.parameter_changed.emit(
                "Resolution", self.res_selector.itemData(idx)
            )
        )
        self.exposure_box.editingFinished.connect(
            lambda: self.parameter_changed.emit(
                "ExposureTime", int(self.exposure_box.value() * 1000)
            )
        )
        self.auto_exposure_cb.toggled.connect(
            lambda chk: self.parameter_changed.emit("AutoExposure", chk)
        )
        self.gain_box.valueChanged.connect(
            lambda v: self.parameter_changed.emit("Gain", v)
        )

    def populate_camera_list(self):
        """
        Enumerate available TIS/IC4 cameras and populate the device combo.
        """
        self.cam_selector.blockSignals(True)
        # clear everything and re-add placeholder
        self.cam_selector.clear()
        self.cam_selector.addItem("Select Camera", None)

        # No IC4 backend
        if not ic4:
            self.cam_selector.addItem("IC4 library unavailable", None)
            self.cam_selector.blockSignals(False)
            # ensure placeholder is selected; user then has to pick the real camera at index 1
            self.cam_selector.setCurrentIndex(0)
            return
        try:
            devices = ic4.DeviceEnum.devices()
        except Exception as e:
            log.error(f"Failed to enumerate cameras: {e}")
            devices = []

        if not devices:
            self.cam_selector.addItem("No cameras found", None)
        else:
            for dev in devices:
                label = f"{dev.model_name} (SN:{dev.serial})"
                self.cam_selector.addItem(label, dev)

    def disable_all_controls(self):
        """
        Disable all camera-related controls (used when no camera is active).
        """
        # Grey out adjustments tab
        self.tabs.setTabEnabled(1, False)
        # Disable individual adjustment widgets
        for w in (self.exposure_box, self.auto_exposure_cb, self.gain_box):
            w.setEnabled(False)
        # Reset and disable resolution selector
        self.res_selector.blockSignals(True)
        self.res_selector.clear()
        self.res_selector.addItem("N/A", None)
        self.res_selector.setEnabled(False)
        self.res_selector.blockSignals(False)
        # Optionally disable camera selector until repopulated
        self.cam_selector.setEnabled(True)

    def update_camera_resolutions_list(self, resolutions):
        """
        Populate the resolution combo based on the active camera's supported modes.
        """
        self.res_selector.blockSignals(True)
        self.res_selector.clear()
        if not resolutions:
            self.res_selector.addItem("N/A", None)
            self.res_selector.setEnabled(False)
        else:
            for res in resolutions:
                # resolution string e.g. '1024x768@30fps'
                self.res_selector.addItem(res, res)
            self.res_selector.setEnabled(True)
        self.res_selector.blockSignals(False)
        # now that a valid camera is selected, enable adjustments tab
        self.tabs.setTabEnabled(1, True)

    def update_camera_properties_ui(self, props: dict):
        """
        Sync the exposure, gain, and auto-exposure widgets with camera properties.
        """
        # ExposureTime comes in microseconds or as reported by backend
        if "ExposureTime" in props:
            self.exposure_box.blockSignals(True)
            # convert to ms for display
            try:
                self.exposure_box.setValue(props["ExposureTime"] / 1000.0)
            except Exception:
                pass
            self.exposure_box.blockSignals(False)
        # Gain in dB
        if "Gain" in props:
            self.gain_box.blockSignals(True)
            try:
                self.gain_box.setValue(props["Gain"])
            except Exception:
                pass
            self.gain_box.blockSignals(False)
        # AutoExposure boolean
        if "AutoExposure" in props:
            self.auto_exposure_cb.blockSignals(True)
            try:
                self.auto_exposure_cb.setChecked(bool(props["AutoExposure"]))
            except Exception:
                pass
            self.auto_exposure_cb.blockSignals(False)
        # Ensure adjustments controls are enabled
        self.tabs.setTabEnabled(1, True)
