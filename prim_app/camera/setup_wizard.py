# PRIM-QTAPP/prim_app/camera/setup_wizard.py
import os
import json
from PyQt5.QtWidgets import (
    QApplication,
    QWizard,
    QWizardPage,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QLabel,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
    QWidget,
    QTextEdit,
)
from PyQt5.QtCore import Qt

# Camera profiles directory from config
from utils.config import CAMERA_PROFILES_DIR

# Import the camera profiling utilities (camera_profiler.py should be on sys.path)
from camera_profiler import profile_camera, get_camera_node_map, test_capture


class CTIPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Locate GenTL/CTI Driver")
        layout = QHBoxLayout()
        self.ctiPathEdit = QLineEdit()
        browseBtn = QPushButton("Browse…")
        browseBtn.clicked.connect(self.browse_cti)
        layout.addWidget(QLabel("CTI Path:"))
        layout.addWidget(self.ctiPathEdit)
        layout.addWidget(browseBtn)
        self.setLayout(layout)

    def browse_cti(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select CTI File", filter="CTI Files (*.cti)"
        )
        if path:
            self.ctiPathEdit.setText(path)

    def validatePage(self):
        path = self.ctiPathEdit.text().strip()
        if not os.path.isfile(path) or not path.lower().endswith(".cti"):
            QMessageBox.warning(
                self, "Invalid File", "Please select a valid .cti file."
            )
            return False
        self.wizard().settings["ctiPath"] = path
        return True


class CameraScanPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Scan and Select Camera")
        layout = QVBoxLayout()
        scanBtn = QPushButton("Scan Cameras")
        scanBtn.clicked.connect(self.scan_cameras)
        self.cameraCombo = QComboBox()
        layout.addWidget(scanBtn)
        layout.addWidget(QLabel("Available Cameras:"))
        layout.addWidget(self.cameraCombo)
        self.setLayout(layout)

    def scan_cameras(self):
        cti = self.wizard().settings.get("ctiPath")
        try:
            cams = profile_camera(cti)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Camera scan failed:\n{e}")
            return
        self.cameraCombo.clear()
        for cam in cams:
            desc = f"{cam['model']} (SN: {cam['serial']})"
            self.cameraCombo.addItem(desc, cam)

    def validatePage(self):
        idx = self.cameraCombo.currentIndex()
        if idx < 0:
            QMessageBox.warning(self, "No Camera", "Please scan and select a camera.")
            return False
        cam = self.cameraCombo.currentData()
        self.wizard().settings.update(
            {"cameraModel": cam["model"], "cameraSerialPattern": cam["serial"]}
        )
        return True


class DefaultsPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Configure Default Settings")
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

    def initializePage(self):
        self.layout.addWidget(QLabel("Exposure Auto:"))
        self.expAutoCombo = QComboBox()
        self.expAutoCombo.addItems(["Off", "Continuous"])
        self.layout.addWidget(self.expAutoCombo)

        self.layout.addWidget(QLabel("Exposure Time (ms):"))
        self.expTimeSpin = QDoubleSpinBox()
        self.expTimeSpin.setRange(1, 60000)
        self.expTimeSpin.setValue(20)
        self.layout.addWidget(self.expTimeSpin)

        self.layout.addWidget(QLabel("Pixel Format:"))
        self.pixFmtCombo = QComboBox()
        self.layout.addWidget(self.pixFmtCombo)

        nodes = get_camera_node_map(
            self.wizard().settings["ctiPath"],
            self.wizard().settings["cameraModel"],
            self.wizard().settings["cameraSerialPattern"],
        )
        for opt in nodes.get("PixelFormat", {}).get("options", []):
            self.pixFmtCombo.addItem(opt)

        self.layout.addWidget(QLabel("Width:"))
        self.widthSpin = QSpinBox()
        wmax = nodes.get("Width", {}).get("max", 10000)
        self.widthSpin.setRange(1, wmax)
        self.widthSpin.setValue(nodes.get("Width", {}).get("current", wmax))
        self.layout.addWidget(self.widthSpin)

        self.layout.addWidget(QLabel("Height:"))
        self.heightSpin = QSpinBox()
        hmax = nodes.get("Height", {}).get("max", 10000)
        self.heightSpin.setRange(1, hmax)
        self.heightSpin.setValue(nodes.get("Height", {}).get("current", hmax))
        self.layout.addWidget(self.heightSpin)

    def validatePage(self):
        self.wizard().settings["defaults"] = {
            "ExposureAuto": self.expAutoCombo.currentText(),
            "ExposureTime": self.expTimeSpin.value(),
            "PixelFormat": self.pixFmtCombo.currentText(),
            "Width": self.widthSpin.value(),
            "Height": self.heightSpin.value(),
        }
        return True


class AdvancedSettingsPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Advanced Settings (Optional)")
        self.area = QScrollArea()
        self.container = QWidget()
        self.layout = QVBoxLayout(self.container)
        self.area.setWidget(self.container)
        self.area.setWidgetResizable(True)
        main = QVBoxLayout()
        main.addWidget(self.area)
        self.setLayout(main)
        self.nodeWidgets = {}

    def initializePage(self):
        self.nodeWidgets.clear()
        nodes = get_camera_node_map(
            self.wizard().settings["ctiPath"],
            self.wizard().settings["cameraModel"],
            self.wizard().settings["cameraSerialPattern"],
        )
        defaults = set(self.wizard().settings.get("defaults", {}).keys())
        for name, info in nodes.items():
            if name in defaults or info.get("type") in ("ICategory", "ICommand"):
                continue
            widget = None
            ntype = info.get("type")
            if ntype == "IEnumeration":
                widget = QComboBox()
                for opt in info.get("options", []):
                    widget.addItem(opt)
                widget.setCurrentText(info.get("current", ""))
            elif ntype in ("IInteger", "IFloat"):
                if ntype == "IInteger":
                    widget = QSpinBox()
                    widget.setRange(info.get("min", 0), info.get("max", 1000000))
                    widget.setValue(info.get("current", 0))
                else:
                    widget = QDoubleSpinBox()
                    widget.setRange(info.get("min", 0.0), info.get("max", 1e6))
                    widget.setValue(info.get("current", 0.0))
            elif ntype == "IBoolean":
                widget = QCheckBox()
                widget.setChecked(info.get("current", False))
            if widget is not None:
                label = QLab
