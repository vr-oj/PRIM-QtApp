import os
import json
import logging
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
from camera.camera_profiler import profile_camera, get_camera_node_map, test_capture

module_log = logging.getLogger(__name__)


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
            cams = profile_camera()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Camera scan failed:\n{e}")
            module_log.error(f"Camera scan error: {e}")
            return
        self.cameraCombo.clear()
        if not cams:
            self.cameraCombo.addItem("No IC4 cameras found.")
            self.cameraCombo.setEnabled(False)
        else:
            self.cameraCombo.setEnabled(True)
            for cam in cams:
                desc = f"{cam['model']} (SN: {cam['serial'] or 'unknown'})"
                self.cameraCombo.addItem(desc, cam)

    def validatePage(self):
        data = self.cameraCombo.currentData()
        if not data or not isinstance(data, dict):
            QMessageBox.warning(
                self, "No Camera", "Please scan and select a valid camera."
            )
            return False
        model = data.get("model")
        serial = data.get("serial") or model
        self.wizard().settings.update(
            {
                "cameraModel": model,
                "cameraSerialPattern": serial,
            }
        )
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
        self.expTimeSpin.setRange(1, 10_000_000)
        self.expTimeSpin.setValue(20_000)
        self.expTimeSpin.setSingleStep(100)

        self.gainSpin = QDoubleSpinBox()
        self.gainSpin.setSuffix(" dB")
        self.gainSpin.setRange(0, 100)
        self.gainSpin.setDecimals(1)

        self.fpsSpin = QDoubleSpinBox()
        self.fpsSpin.setSuffix(" FPS")
        self.fpsSpin.setRange(1, 500)
        self.fpsSpin.setDecimals(1)

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
        s = self.wizard().settings
        pattern = s.get("cameraSerialPattern")
        if not pattern:
            QMessageBox.critical(self, "Error", "Camera not selected.")
            return
        nodes = get_camera_node_map(s["cameraModel"], pattern) or {}

        # Populate or fallback
        self.pixFmtCombo.clear()
        options = nodes.get("PixelFormat", {}).get("options", ["Mono8", "BayerRG8"])
        self.pixFmtCombo.addItems([str(o) for o in options])

        for name, widget in [
            ("Width", self.widthSpin),
            ("Height", self.heightSpin),
            ("ExposureTime", self.expTimeSpin),
            ("Gain", self.gainSpin),
            ("AcquisitionFrameRate", self.fpsSpin),
        ]:
            info = nodes.get(name, {})
            if "min" in info and "max" in info:
                widget.setRange(info["min"], info["max"])
            widget.setValue(info.get("current", widget.value()))

        # ExposureAuto
        cur = nodes.get("ExposureAuto", {}).get("current", "Off")
        if isinstance(cur, bool):
            cur = "Continuous" if cur else "Off"
        idx = self.expAutoCombo.findText(str(cur))
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

        s = self.wizard().settings
        nodes = get_camera_node_map(s["cameraModel"], s["cameraSerialPattern"]) or {}
        defaults = set(self.wizard().settings.get("defaults", {}).keys())

        for name, info in sorted(nodes.items()):
            if name in defaults or not info.get("type"):
                continue
            widget = None
            t = info.get("type")
            cur = info.get("current")
            if t == "IEnumeration":
                widget = QComboBox()
                widget.addItems([str(o) for o in info.get("options", [])])
                idx = widget.findText(str(cur))
                if idx >= 0:
                    widget.setCurrentIndex(idx)
            elif t == "IInteger":
                widget = QSpinBox()
                widget.setRange(info.get("min", 0), info.get("max", 0))
                widget.setValue(cur or 0)
            elif t == "IFloat":
                widget = QDoubleSpinBox()
                widget.setRange(info.get("min", 0), info.get("max", 0))
                widget.setValue(cur or 0)
            elif t == "IBoolean":
                widget = QCheckBox()
                widget.setChecked(bool(cur))
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
        self.testBtn = QPushButton("Test Capture")
        self.testBtn.clicked.connect(self.run_test)
        layout.addWidget(self.infoLabel)
        layout.addWidget(self.testBtn)
        self.tested_successfully = False

    def run_test(self):
        self.testBtn.setEnabled(False)
        self.infoLabel.setText("Attempting test capture...")
        QApplication.processEvents()
        s = self.wizard().settings
        settings = {**s.get("defaults", {}), **s.get("advanced", {})}
        try:
            ok = test_capture(s["cameraModel"], s["cameraSerialPattern"], settings)
            self.tested_successfully = ok
            self.infoLabel.setText(
                "Test capture SUCCEEDED!" if ok else "Test capture FAILED."
            )
            if not ok:
                QMessageBox.warning(self, "Capture Failed", "No frame returned.")
        except Exception as e:
            module_log.error(f"Test capture exception: {e}")
            QMessageBox.critical(self, "Capture Exception", str(e))
            self.infoLabel.setText(f"Error: {e}")
            self.tested_successfully = False
        finally:
            self.testBtn.setEnabled(True)

    def validatePage(self):
        if not self.tested_successfully:
            return (
                QMessageBox.warning(
                    self,
                    "Test Not Successful",
                    "Proceed anyway?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                == QMessageBox.Yes
            )
        return True


class SummaryPage(QWizardPage):
    """Page 5: Save the configured profile to disk"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Save Camera Profile")
        layout = QFormLayout(self)
        self.nameEdit = QLineEdit()
        layout.addRow("Profile Name:", self.nameEdit)

    def initializePage(self):
        s = self.wizard().settings
        model = s.get("cameraModel", "Camera")
        serial = s.get("cameraSerialPattern", "")
        name = f"{model}_{serial}_Profile".replace(" ", "_")
        self.nameEdit.setText(name)

    def validatePage(self):
        name = self.nameEdit.text().strip()
        if not name:
            QMessageBox.warning(self, "Profile Name Required", "Enter a profile name.")
            return False
        s = self.wizard().settings
        profile = {
            "profileName": name,
            "model": s.get("cameraModel"),
            "serialPattern": s.get("cameraSerialPattern"),
            "defaults": s.get("defaults", {}),
            "advanced": s.get("advanced", {}),
            "ctiPathUsed": load_app_setting(SETTING_CTI_PATH),
        }
        os.makedirs(CAMERA_PROFILES_DIR, exist_ok=True)
        filename = f"{name}.json"
        path = os.path.join(CAMERA_PROFILES_DIR, filename)
        if os.path.exists(path):
            if QMessageBox.No == QMessageBox.warning(
                self,
                "Overwrite?",
                f"'{filename}' exists. Overwrite?",
                QMessageBox.Yes | QMessageBox.No,
            ):
                return False
        try:
            with open(path, "w") as f:
                json.dump(profile, f, indent=4)
            QMessageBox.information(self, "Profile Saved", f"Saved to {path}")
            s["profileNameSavedAs"] = name
            return True
        except Exception as e:
            module_log.error(f"Save profile error: {e}")
            QMessageBox.critical(self, "Save Error", str(e))
            return False


class CameraSetupWizard(QWizard):
    """Top-level wizard orchestrating camera setup"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Camera Setup Wizard")
        self.settings = {}
        self.setWizardStyle(QWizard.ModernStyle)
        self.addPage(CameraScanPage())
        self.addPage(DefaultsPage())
        self.addPage(AdvancedSettingsPage())
        self.addPage(TestCapturePage())
        self.addPage(SummaryPage())
