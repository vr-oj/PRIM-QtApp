import os
import json
import logging
import imagingcontrol4 as ic4
from PyQt5.QtWidgets import (
    QApplication,
    QWizard,
    QWizardPage,
    QLabel,
    QComboBox,
    QPushButton,
    QVBoxLayout,
    QFormLayout,
    QLineEdit,
    QFileDialog,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QScrollArea,
    QWidget,
    QMessageBox,
)

from utils.config import CAMERA_PROFILES_DIR
from utils.app_settings import load_app_setting, SETTING_CTI_PATH

module_log = logging.getLogger(__name__)

# Ensure CTI path is set before using wizard
cti_path = load_app_setting(SETTING_CTI_PATH)
if cti_path:
    os.environ["GENICAM_GENTL64_PATH"] = os.path.dirname(cti_path)
else:
    QMessageBox.warning(None, "CTI Not Configured", "No CTI path found in settings.")

# Initialize IC4 library if not already initialized
try:
    ic4.Library.init()
except RuntimeError:
    # Already initialized in prim_app.setup
    pass
except ic4.IC4Exception as e:
    QMessageBox.critical(None, "IC4 Init Error", f"{e.code}: {e.message}")
    raise


class CameraScanPage(QWizardPage):
    """Page 1: Scan for available IC4 cameras"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Scan and Select Camera")
        layout = QVBoxLayout(self)
        self.scanBtn = QPushButton("Scan for IC4 Cameras")
        self.scanBtn.clicked.connect(self.scan_cameras)
        self.cameraCombo = QComboBox()
        layout.addWidget(self.scanBtn)
        layout.addWidget(QLabel("Available Cameras:"))
        layout.addWidget(self.cameraCombo)

    def scan_cameras(self):
        try:
            devices = ic4.Device.enumerate()
        except ic4.IC4Exception as e:
            QMessageBox.critical(self, "IC4 Error", f"{e.code}: {e.message}")
            module_log.error(f"Camera scan error: {e}")
            return
        self.cameraCombo.clear()
        if not devices:
            self.cameraCombo.addItem("No IC4 cameras found.")
            self.cameraCombo.setEnabled(False)
        else:
            self.cameraCombo.setEnabled(True)
            for dev in devices:
                desc = f"{dev.model_name} (SN: {dev.serial_number})"
                self.cameraCombo.addItem(desc, dev)

    def validatePage(self):
        dev = self.cameraCombo.currentData()
        if not dev:
            QMessageBox.warning(
                self, "No Camera", "Please scan and select a valid camera."
            )
            return False
        # Store the DeviceInfo object
        self.wizard().settings["device_info"] = dev
        return True


class DefaultsPage(QWizardPage):
    """Page 2: Configure default GenICam settings"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Configure Default Settings")
        self.form = QFormLayout(self)

        # Widgets
        self.expAutoCombo = QComboBox()
        self.expAutoCombo.addItems(["Off", "Continuous"])
        self.expTimeSpin = QDoubleSpinBox()
        self.expTimeSpin.setSuffix(" µs")
        self.gainSpin = QDoubleSpinBox()
        self.gainSpin.setSuffix(" dB")
        self.fpsSpin = QDoubleSpinBox()
        self.fpsSpin.setSuffix(" FPS")
        self.pixFmtCombo = QComboBox()
        self.widthSpin = QSpinBox()
        self.heightSpin = QSpinBox()

        # Layout
        for label, widget in [
            ("Exposure Auto:", self.expAutoCombo),
            ("Exposure Time:", self.expTimeSpin),
            ("Gain:", self.gainSpin),
            ("Target FPS:", self.fpsSpin),
            ("Pixel Format:", self.pixFmtCombo),
            ("Width:", self.widthSpin),
            ("Height:", self.heightSpin),
        ]:
            self.form.addRow(label, widget)

    def initializePage(self):
        dev = self.wizard().settings.get("device_info")
        if not dev:
            QMessageBox.critical(self, "Error", "Camera not selected.")
            return
        grabber = ic4.Grabber(dev)
        grabber.device_open()
        node_map = grabber.node_map

        # PixelFormat options
        pix_node = node_map.get("PixelFormat")
        self.pixFmtCombo.clear()
        if pix_node:
            self.pixFmtCombo.addItems([str(opt) for opt in pix_node.options])
            cur = str(pix_node.value)
            idx = self.pixFmtCombo.findText(cur)
            if idx >= 0:
                self.pixFmtCombo.setCurrentIndex(idx)

        # Numeric nodes
        for name, widget in [
            ("Width", self.widthSpin),
            ("Height", self.heightSpin),
            ("ExposureTime", self.expTimeSpin),
            ("Gain", self.gainSpin),
            ("AcquisitionFrameRate", self.fpsSpin),
        ]:
            node = node_map.get(name)
            if node:
                widget.setRange(node.min, node.max)
                widget.setValue(node.value)

        # Exposure Auto enumeration
        exp_node = node_map.get("ExposureAuto")
        if exp_node:
            self.expAutoCombo.clear()
            self.expAutoCombo.addItems([str(o) for o in exp_node.options])
            cur = str(exp_node.value)
            idx = self.expAutoCombo.findText(cur)
            if idx >= 0:
                self.expAutoCombo.setCurrentIndex(idx)

    def validatePage(self):
        self.wizard().settings["defaults"] = {
            "ExposureAuto": self.expAutoCombo.currentText(),
            "ExposureTime": self.expTimeSpin.value(),
            "Gain": self.gainSpin.value(),
            "AcquisitionFrameRate": self.fpsSpin.value(),
            "PixelFormat": self.pixFmtCombo.currentText(),
            "Width": self.widthSpin.value(),
            "Height": self.heightSpin.value(),
        }
        return True


class AdvancedSettingsPage(QWizardPage):
    """Page 3: Optional advanced GenICam nodes"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Advanced Settings (Optional)")
        self.scroll = QScrollArea()
        self.container = QWidget()
        self.form = QFormLayout(self.container)
        self.scroll.setWidget(self.container)
        self.scroll.setWidgetResizable(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.scroll)
        self.nodeWidgets = {}

    def initializePage(self):
        # Clear old
        while self.form.count():
            item = self.form.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.nodeWidgets.clear()

        dev = self.wizard().settings.get("device_info")
        if not dev:
            return
        grabber = ic4.Grabber(dev)
        grabber.device_open()
        node_map = grabber.node_map
        defaults = set(self.wizard().settings.get("defaults", {}).keys())

        for name, node in sorted(node_map.items()):
            if name in defaults or node is None:
                continue
            widget = None
            if node.type == "IEnumeration":
                widget = QComboBox()
                widget.addItems([str(o) for o in node.options])
                idx = widget.findText(str(node.value))
                if idx >= 0:
                    widget.setCurrentIndex(idx)
            elif node.type == "IInteger":
                widget = QSpinBox()
                widget.setRange(node.min, node.max)
                widget.setValue(node.value)
            elif node.type == "IFloat":
                widget = QDoubleSpinBox()
                widget.setRange(node.min, node.max)
                widget.setValue(node.value)
            elif node.type == "IBoolean":
                widget = QCheckBox()
                widget.setChecked(bool(node.value))
            if widget:
                self.form.addRow(f"{name}:", widget)
                self.nodeWidgets[name] = widget

    def validatePage(self):
        adv = {}
        for name, w in self.nodeWidgets.items():
            if isinstance(w, QComboBox):
                adv[name] = w.currentText()
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                adv[name] = w.value()
            elif isinstance(w, QCheckBox):
                adv[name] = w.isChecked()
        self.wizard().settings["advanced"] = adv
        return True


class TestCapturePage(QWizardPage):
    """Page 4: Verify camera settings with a test image grab"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Test Capture")
        layout = QVBoxLayout(self)
        self.infoLabel = QLabel(
            "Click 'Test Capture' to grab a frame with the current settings."
        )
        self.test
