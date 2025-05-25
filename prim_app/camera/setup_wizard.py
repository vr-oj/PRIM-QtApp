# prim_app/camera/setup_wizard.py

import os
import json
from PyQt5.QtWidgets import (
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
    QTextEdit,
    QDialogButtonBox,
)
from PyQt5.QtCore import Qt

from utils.config import CAMERA_PROFILES_DIR
from camera.camera_profiler import profile_camera, get_camera_node_map, test_capture


class CameraScanPage(QWizardPage):
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
            cams = profile_camera()
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
        self.wizard().settings["cameraModel"] = cam["model"]
        self.wizard().settings["cameraSerialPattern"] = cam["serial"]
        return True


class DefaultsPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Configure Default Settings")
        self.form = QFormLayout(self)
        self.expAutoCombo = QComboBox()
        self.expAutoCombo.addItems(["Off", "Continuous"])
        self.expTimeSpin = QDoubleSpinBox()
        self.expTimeSpin.setRange(1, 60000)
        self.expTimeSpin.setValue(20)
        self.pixFmtCombo = QComboBox()
        self.widthSpin = QSpinBox()
        self.heightSpin = QSpinBox()

        self.form.addRow("Exposure Auto:", self.expAutoCombo)
        self.form.addRow("Exposure Time (ms):", self.expTimeSpin)
        self.form.addRow("Pixel Format:", self.pixFmtCombo)
        self.form.addRow("Width:", self.widthSpin)
        self.form.addRow("Height:", self.heightSpin)

    def initializePage(self):
        nodes = get_camera_node_map(
            self.wizard().settings["cameraModel"],
            self.wizard().settings["cameraSerialPattern"],
        )
        # Populate pixel formats
        self.pixFmtCombo.clear()
        for fmt in nodes.get("PIXEL_FORMAT", {}).get("options", []):
            self.pixFmtCombo.addItem(fmt)
        # Width/Height ranges
        winfo = nodes.get("WIDTH", {})
        hinfo = nodes.get("HEIGHT", {})
        self.widthSpin.setRange(1, winfo.get("max", 10000))
        self.widthSpin.setValue(winfo.get("current", winfo.get("max", 10000)))
        self.heightSpin.setRange(1, hinfo.get("max", 10000))
        self.heightSpin.setValue(hinfo.get("current", hinfo.get("max", 10000)))

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
        main = QVBoxLayout(self)
        main.addWidget(self.area)
        self.nodeWidgets = {}

    def initializePage(self):
        for w in self.nodeWidgets.values():
            w.deleteLater()
        self.nodeWidgets.clear()
        nodes = get_camera_node_map(
            self.wizard().settings["cameraModel"],
            self.wizard().settings["cameraSerialPattern"],
        )
        defaults = set(self.wizard().settings.get("defaults", {}).keys())
        for name, info in nodes.items():
            if name in defaults or info.get("type") in ("ICategory", "ICommand"):
                continue
            widget = None
            t = info.get("type")
            if t == "IEnumeration":
                widget = QComboBox()
                for opt in info.get("options", []):
                    widget.addItem(opt)
                widget.setCurrentText(info.get("current", ""))
            elif t == "IInteger":
                widget = QSpinBox()
                widget.setRange(info.get("min", 0), info.get("max", 1000000))
                widget.setValue(info.get("current", 0))
            elif t == "IFloat":
                widget = QDoubleSpinBox()
                widget.setRange(info.get("min", 0.0), info.get("max", 1e6))
                widget.setValue(info.get("current", 0.0))
            elif t == "IBoolean":
                widget = QCheckBox()
                widget.setChecked(info.get("current", False))
            if widget:
                self.layout.addWidget(QLabel(name))
                self.layout.addWidget(widget)
                self.nodeWidgets[name] = widget

    def validatePage(self):
        adv = {}
        for name, w in self.nodeWidgets.items():
            if isinstance(w, QComboBox):
                adv[name] = w.currentText()
            elif hasattr(w, "value"):
                adv[name] = w.value()
            elif isinstance(w, QCheckBox):
                adv[name] = w.isChecked()
        self.wizard().settings["advanced"] = adv
        return True


class TestCapturePage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Test Capture")
        layout = QVBoxLayout(self)
        self.infoLabel = QLabel("Click to grab a test frame.")
        self.testBtn = QPushButton("Test Capture")
        self.testBtn.clicked.connect(self.run_test)
        layout.addWidget(self.infoLabel)
        layout.addWidget(self.testBtn)
        self.tested = False

    def run_test(self):
        self.testBtn.setEnabled(False)
        settings = {
            **self.wizard().settings.get("defaults", {}),
            **self.wizard().settings.get("advanced", {}),
        }
        try:
            ok = test_capture(
                self.wizard().settings["cameraModel"],
                self.wizard().settings["cameraSerialPattern"],
                settings,
            )
            if ok:
                self.infoLabel.setText("Test capture succeeded!")
                self.tested = True
            else:
                self.infoLabel.setText("Test capture failed.")
        except Exception as e:
            QMessageBox.critical(self, "Capture Error", str(e))
        self.testBtn.setEnabled(True)

    def validatePage(self):
        if not self.tested:
            QMessageBox.warning(
                self, "Not Tested", "Please perform a test capture first."
            )
            return False
        return True


class SummaryPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Save Camera Profile")
        layout = QFormLayout(self)
        self.nameEdit = QLineEdit()
        layout.addRow("Profile Name:", self.nameEdit)

    def validatePage(self):
        name = self.nameEdit.text().strip()
        if not name:
            QMessageBox.warning(self, "Profile Name", "Please enter a profile name.")
            return False
        s = self.wizard().settings
        profile = {
            "profileName": name,
            "model": s["cameraModel"],
            "serialPattern": s["cameraSerialPattern"],
            "defaults": s.get("defaults", {}),
            "advanced": s.get("advanced", {}),
        }
        os.makedirs(CAMERA_PROFILES_DIR, exist_ok=True)
        path = os.path.join(CAMERA_PROFILES_DIR, f"{name.replace(' ','_')}.json")
        with open(path, "w") as f:
            json.dump(profile, f, indent=4)
        QMessageBox.information(self, "Saved", f"Camera profile saved to {path}")
        return True


class CameraSetupWizard(QWizard):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Camera Setup Wizard")
        self.settings = {}
        self.setWizardStyle(QWizard.ModernStyle)
        # Only pages that actually matter now:
        self.addPage(CameraScanPage())
        self.addPage(DefaultsPage())
        self.addPage(AdvancedSettingsPage())
        self.addPage(TestCapturePage())
        self.addPage(SummaryPage())
