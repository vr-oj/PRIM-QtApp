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

        self.cam_selector = QComboBox()
        self.cam_selector.setToolTip("Select Camera Device")
        src_layout.addRow("Device:", self.cam_selector)

        self.res_selector = QComboBox()
        self.res_selector.setToolTip("Select Resolution and Format")
        src_layout.addRow("Resolution:", self.res_selector)

        self.current_res_label = QLabel("––")
        src_layout.addRow("Current:", self.current_res_label)

        self.tabs.addTab(src_tab, "Source")

        # -- Adjustments Tab --
        adj_tab = QWidget()
        adj_layout = QFormLayout(adj_tab)

        self.exposure_box = QDoubleSpinBox()
        self.exposure_box.setDecimals(1)
        self.exposure_box.setSuffix(" ms")
        self.exposure_box.setRange(0.1, 10000.0)
        self.exposure_box.setKeyboardTracking(False)
        adj_layout.addRow("Exposure:", self.exposure_box)

        self.auto_exposure_cb = QCheckBox("Auto Exposure")
        adj_layout.addRow(self.auto_exposure_cb)

        self.gain_box = QDoubleSpinBox()
        self.gain_box.setDecimals(1)
        self.gain_box.setKeyboardTracking(False)
        adj_layout.addRow("Gain (dB):", self.gain_box)

        self.tabs.addTab(adj_tab, "Adjustments")
        adj_tab.setEnabled(False)

        # Connect UI signals to parameter_changed
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
