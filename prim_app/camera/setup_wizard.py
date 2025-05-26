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
    # QTextEdit, # Not used in provided snippet of SummaryPage
    # QDialogButtonBox, # Not used in provided snippet of SummaryPage
)

# from PyQt5.QtCore import Qt # Not used in provided snippet of SummaryPage

from utils.config import CAMERA_PROFILES_DIR
from camera.camera_profiler import profile_camera, get_camera_node_map, test_capture

# Import app_settings to get the current CTI path
from utils.app_settings import load_app_setting, SETTING_CTI_PATH


# ... (CameraScanPage, DefaultsPage, AdvancedSettingsPage, TestCapturePage classes remain as you provided) ...
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
            # Assuming IC4 library is initialized before wizard runs if needed by profile_camera
            cams = profile_camera()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Camera scan failed:\n{e}")
            return
        self.cameraCombo.clear()
        if not cams:
            self.cameraCombo.addItem("No IC4 cameras found.")
            self.cameraCombo.setEnabled(False)
        else:
            self.cameraCombo.setEnabled(True)
            for cam in cams:
                desc = f"{cam['model']} (SN: {cam['serial']})"
                self.cameraCombo.addItem(desc, cam)  # Store dict as item data

    def validatePage(self):
        idx = self.cameraCombo.currentIndex()
        if (
            idx < 0 or not self.cameraCombo.currentData()
        ):  # Check if currentData is valid
            QMessageBox.warning(
                self, "No Camera", "Please scan and select a valid camera."
            )
            return False
        cam_data = self.cameraCombo.currentData()  # This is the dict
        if (
            not isinstance(cam_data, dict)
            or "model" not in cam_data
            or "serial" not in cam_data
        ):
            QMessageBox.warning(
                self,
                "Invalid Camera Data",
                "Selected camera data is invalid. Please re-scan.",
            )
            return False

        self.wizard().settings["cameraModel"] = cam_data["model"]
        self.wizard().settings["cameraSerialPattern"] = cam_data["serial"]
        return True


class DefaultsPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Configure Default Settings")
        self.form = QFormLayout(self)
        self.expAutoCombo = QComboBox()
        self.expAutoCombo.addItems(["Off", "Continuous"])  # Common GenICam values
        self.expTimeSpin = QDoubleSpinBox()
        self.expTimeSpin.setSuffix(
            " µs"
        )  # Exposure is often in microseconds for GenICam
        self.expTimeSpin.setRange(1, 10000000)  # Example: 1µs to 10s
        self.expTimeSpin.setValue(20000)  # Example: 20ms
        self.expTimeSpin.setSingleStep(100)

        self.pixFmtCombo = QComboBox()
        self.widthSpin = QSpinBox()
        self.heightSpin = QSpinBox()

        self.gainSpin = QDoubleSpinBox()  # Added Gain
        self.gainSpin.setSuffix(" dB")  # Or unitless depending on camera
        self.gainSpin.setRange(0, 100)  # Example range
        self.gainSpin.setDecimals(1)

        self.fpsSpin = QDoubleSpinBox()  # Added FPS
        self.fpsSpin.setSuffix(" FPS")
        self.fpsSpin.setRange(1, 500)  # Example range
        self.fpsSpin.setDecimals(1)

        self.form.addRow("Exposure Auto:", self.expAutoCombo)
        self.form.addRow("Exposure Time:", self.expTimeSpin)  # µs
        self.form.addRow("Gain:", self.gainSpin)
        self.form.addRow("Target FPS:", self.fpsSpin)
        self.form.addRow("Pixel Format:", self.pixFmtCombo)
        self.form.addRow("Width:", self.widthSpin)
        self.form.addRow("Height:", self.heightSpin)

    def initializePage(self):
        # This page relies on get_camera_node_map which needs IC4 initialized and camera selected
        if not self.wizard().settings.get("cameraSerialPattern"):
            QMessageBox.critical(self, "Error", "Camera not selected in previous step.")
            # Potentially go back: self.wizard().back() - but QWizard handles this if validatePage fails
            return

        nodes = get_camera_node_map(  # This needs to work with the selected camera
            self.wizard().settings["cameraModel"],
            self.wizard().settings["cameraSerialPattern"],
        )
        if not nodes:
            QMessageBox.warning(
                self,
                "Node Map Error",
                "Could not retrieve camera properties (node map). Defaults may be incorrect.",
            )
            # Fallback to some very generic ranges if nodes is empty or properties are missing
            self.pixFmtCombo.clear()
            self.pixFmtCombo.addItems(["Mono8", "BayerRG8"])  # Generic fallbacks
            self.widthSpin.setRange(1, 10000)
            self.widthSpin.setValue(640)
            self.heightSpin.setRange(1, 10000)
            self.heightSpin.setValue(480)
            self.expTimeSpin.setRange(1, 10000000)
            self.expTimeSpin.setValue(
                nodes.get("ExposureTime", {}).get("current", 20000)
            )
            self.gainSpin.setRange(0, 100)
            self.gainSpin.setValue(nodes.get("Gain", {}).get("current", 0))
            self.fpsSpin.setRange(1, 500)
            self.fpsSpin.setValue(
                nodes.get("AcquisitionFrameRate", {}).get("current", 30)
            )

            # ExposureAuto needs to map to string values for combo
            exp_auto_val = nodes.get("ExposureAuto", {}).get("current", "Off")
            if isinstance(exp_auto_val, bool):  # if it's bool
                exp_auto_val = "Continuous" if exp_auto_val else "Off"
            idx = self.expAutoCombo.findText(str(exp_auto_val))
            if idx != -1:
                self.expAutoCombo.setCurrentIndex(idx)

            return

        # Populate pixel formats
        self.pixFmtCombo.clear()
        pixel_format_node = nodes.get(
            "PixelFormat", {}
        )  # GenICam names are often like 'PixelFormat'
        if pixel_format_node and "options" in pixel_format_node:
            for fmt in pixel_format_node.get("options", []):
                self.pixFmtCombo.addItem(fmt)
            current_pix_fmt = str(pixel_format_node.get("current", ""))
            idx = self.pixFmtCombo.findText(current_pix_fmt)
            if idx != -1:
                self.pixFmtCombo.setCurrentIndex(idx)
            elif self.pixFmtCombo.count() > 0:
                self.pixFmtCombo.setCurrentIndex(0)
        else:
            self.pixFmtCombo.addItems(["Mono8", "BayerRG8"])  # Fallback

        # Width/Height ranges and current values
        winfo = nodes.get("Width", {})
        hinfo = nodes.get("Height", {})
        self.widthSpin.setRange(winfo.get("min", 1), winfo.get("max", 10000))
        self.widthSpin.setValue(winfo.get("current", winfo.get("default", 640)))
        self.heightSpin.setRange(hinfo.get("min", 1), hinfo.get("max", 10000))
        self.heightSpin.setValue(hinfo.get("current", hinfo.get("default", 480)))

        # Exposure Time
        expinfo = nodes.get("ExposureTime", {})  # Assuming µs
        self.expTimeSpin.setRange(expinfo.get("min", 1), expinfo.get("max", 10000000))
        self.expTimeSpin.setValue(expinfo.get("current", expinfo.get("default", 20000)))

        # Exposure Auto
        exp_auto_info = nodes.get("ExposureAuto", {})
        current_exp_auto = exp_auto_info.get(
            "current", "Off"
        )  # Assuming string value like "Off" or "Continuous"
        # map this to index of self.expAutoCombo
        idx = self.expAutoCombo.findText(str(current_exp_auto))
        if idx != -1:
            self.expAutoCombo.setCurrentIndex(idx)

        # Gain
        gain_info = nodes.get("Gain", {})
        self.gainSpin.setRange(gain_info.get("min", 0), gain_info.get("max", 100))
        self.gainSpin.setValue(gain_info.get("current", gain_info.get("default", 0)))

        # FPS
        fps_info = nodes.get("AcquisitionFrameRate", {})
        self.fpsSpin.setRange(fps_info.get("min", 1), fps_info.get("max", 500))
        self.fpsSpin.setValue(fps_info.get("current", fps_info.get("default", 30)))

    def validatePage(self):
        # Store settings with GenICam standard names if possible
        self.wizard().settings["defaults"] = {
            "ExposureAuto": self.expAutoCombo.currentText(),  # "Off" or "Continuous"
            "ExposureTime": self.expTimeSpin.value(),  # Expecting float (µs)
            "Gain": self.gainSpin.value(),  # Expecting float
            "AcquisitionFrameRate": self.fpsSpin.value(),  # Expecting float
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
        self.layout = QFormLayout(
            self.container
        )  # Changed to QFormLayout for Label: Widget pairs
        self.area.setWidget(self.container)
        self.area.setWidgetResizable(True)
        main_layout = QVBoxLayout(
            self
        )  # Use a different name for the main layout of the page
        main_layout.addWidget(self.area)
        self.nodeWidgets = {}

    def initializePage(self):
        # Clear previous widgets
        for i in reversed(range(self.layout.count())):
            widget_item = self.layout.itemAt(i)
            if widget_item:
                widget = widget_item.widget()
                if widget:
                    widget.deleteLater()
        self.nodeWidgets.clear()

        if not self.wizard().settings.get("cameraSerialPattern"):
            # This should not happen if previous pages validate correctly
            return

        nodes = get_camera_node_map(
            self.wizard().settings["cameraModel"],
            self.wizard().settings["cameraSerialPattern"],
        )
        # Default keys that are handled in DefaultsPage (using GenICam names)
        default_keys = {
            "ExposureAuto",
            "ExposureTime",
            "Gain",
            "AcquisitionFrameRate",
            "PixelFormat",
            "Width",
            "Height",
        }

        for name, info in sorted(nodes.items()):  # Sort for consistent order
            if (
                name in default_keys
                or info.get("type") in ("ICategory", "ICommand")
                or not info.get("type")
            ):
                continue  # Skip defaults, categories, commands, or nodes without a type

            widget = None
            node_type = info.get(
                "type"
            )  # e.g., "IEnumeration", "IInteger", "IFloat", "IBoolean"
            current_val = info.get("current")
            options = info.get("options", [])
            node_min = info.get("min")
            node_max = info.get("max")
            # unit = info.get("unit", "") # If available

            label_text = f"{name}:"  # Add unit to label if present: f"{name} ({unit}):" if unit else f"{name}:"

            if node_type == "IEnumeration":
                widget = QComboBox()
                if options:
                    for opt in options:
                        widget.addItem(str(opt))  # Ensure options are strings
                    idx = widget.findText(str(current_val))
                    if idx != -1:
                        widget.setCurrentIndex(idx)
            elif node_type == "IInteger":
                widget = QSpinBox()
                if node_min is not None and node_max is not None:
                    widget.setRange(int(node_min), int(node_max))
                if current_val is not None:
                    widget.setValue(int(current_val))
            elif node_type == "IFloat":
                widget = QDoubleSpinBox()
                if node_min is not None and node_max is not None:
                    widget.setRange(float(node_min), float(node_max))
                if current_val is not None:
                    widget.setValue(float(current_val))
                widget.setDecimals(
                    info.get("precision", 3)
                )  # Adjust precision if available
            elif node_type == "IBoolean":
                widget = QCheckBox()
                if current_val is not None:
                    widget.setChecked(bool(current_val))
            # Add IString if relevant:
            # elif node_type == "IString":
            #     widget = QLineEdit()
            #     if current_val is not None: widget.setText(str(current_val))

            if widget:
                self.layout.addRow(label_text, widget)
                self.nodeWidgets[name] = widget  # Store widget by its GenICam name

    def validatePage(self):
        adv_settings = {}
        for name, widget_instance in self.nodeWidgets.items():
            if isinstance(widget_instance, QComboBox):
                adv_settings[name] = widget_instance.currentText()
            elif isinstance(widget_instance, (QSpinBox, QDoubleSpinBox)):
                adv_settings[name] = widget_instance.value()
            elif isinstance(widget_instance, QCheckBox):
                adv_settings[name] = widget_instance.isChecked()
            elif isinstance(widget_instance, QLineEdit):  # If IString is added
                adv_settings[name] = widget_instance.text()
        self.wizard().settings["advanced"] = adv_settings
        return True


class TestCapturePage(QWizardPage):
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
        self.tested_successfully = False  # More descriptive flag

    def run_test(self):
        self.testBtn.setEnabled(False)
        self.infoLabel.setText("Attempting test capture...")
        QApplication.processEvents()  # Update UI

        # Consolidate settings from defaults and advanced pages
        # Wizard settings should be up-to-date from previous validatePage calls
        default_settings = self.wizard().settings.get("defaults", {})
        advanced_settings = self.wizard().settings.get("advanced", {})
        current_test_settings = {**default_settings, **advanced_settings}

        camera_model = self.wizard().settings.get("cameraModel")
        camera_serial = self.wizard().settings.get("cameraSerialPattern")

        if not camera_serial:
            QMessageBox.critical(
                self, "Capture Error", "Camera serial not found in wizard settings."
            )
            self.infoLabel.setText("Test capture failed: Missing camera information.")
            self.testBtn.setEnabled(True)
            self.tested_successfully = False
            return

        try:
            # test_capture function should handle applying settings to the camera
            ok = test_capture(camera_model, camera_serial, current_test_settings)
            if ok:
                self.infoLabel.setText("Test capture SUCCEEDED!")
                self.tested_successfully = True
            else:
                self.infoLabel.setText(
                    "Test capture FAILED. Check camera connection and settings."
                )
                self.tested_successfully = False
                QMessageBox.warning(
                    self,
                    "Capture Failed",
                    "The camera did not return a frame. Check settings and ensure the camera is not in use by another application.",
                )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Capture Exception",
                f"An error occurred during test capture:\n{e}",
            )
            self.infoLabel.setText(f"Test capture error: {e}")
            self.tested_successfully = False
        finally:
            self.testBtn.setEnabled(True)

    def validatePage(self):
        if not self.tested_successfully:
            # Allow proceeding even if test fails, but warn
            reply = QMessageBox.warning(
                self,
                "Test Not Successful",
                "The test capture was not successful or not performed. "
                "Do you want to proceed with saving this profile anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            return reply == QMessageBox.Yes
        return True


class SummaryPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Save Camera Profile")
        layout = QFormLayout(self)
        self.nameEdit = QLineEdit()
        self.nameEdit.setPlaceholderText("e.g., DMK_Settings_Lab1")
        layout.addRow("Profile Name:", self.nameEdit)

        # Auto-generate a default name based on camera model
        # This will be set in initializePage if possible

    def initializePage(self):
        cam_model = self.wizard().settings.get("cameraModel", "MyCamera")
        cam_serial = self.wizard().settings.get("cameraSerialPattern", "")
        safe_model = "".join(c if c.isalnum() else "_" for c in cam_model)
        safe_serial_suffix = f"_{cam_serial}" if cam_serial else ""
        default_profile_name = f"{safe_model}{safe_serial_suffix}_Profile"
        self.nameEdit.setText(default_profile_name)

    def validatePage(self):
        name = self.nameEdit.text().strip()
        if not name:
            QMessageBox.warning(
                self,
                "Profile Name Required",
                "Please enter a name for this camera profile.",
            )
            return False

        s = self.wizard().settings
        # Use GenICam standard names in the profile where possible
        profile_defaults = s.get("defaults", {})  # Already uses GenICam names

        profile = {
            "profileName": name,  # This is the user-friendly name for the profile file
            "model": s.get("cameraModel"),
            "serialPattern": s.get("cameraSerialPattern"),
            "defaults": profile_defaults,
            "advanced": s.get(
                "advanced", {}
            ),  # Assumes advanced keys are also GenICam names
            "ctiPathUsed": load_app_setting(
                SETTING_CTI_PATH
            ),  # Save the CTI that was active
        }

        os.makedirs(CAMERA_PROFILES_DIR, exist_ok=True)
        # Sanitize profile name for use as a filename
        safe_filename = (
            "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in name)
            + ".json"
        )
        path = os.path.join(CAMERA_PROFILES_DIR, safe_filename)

        if os.path.exists(path):
            reply = QMessageBox.warning(
                self,
                "Overwrite Profile?",
                f"A profile named '{safe_filename}' already exists. Overwrite?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return False  # Stay on page for user to change name

        try:
            with open(path, "w") as f:
                json.dump(profile, f, indent=4)
            QMessageBox.information(
                self, "Profile Saved", f"Camera profile saved to:\n{path}"
            )
            # Store this profile name as the one to auto-load next time (base name without .json)
            self.wizard().settings["profileNameSavedAs"] = safe_filename.replace(
                ".json", ""
            )
            return True
        except Exception as e:
            QMessageBox.critical(
                self, "Save Error", f"Could not save camera profile:\n{e}"
            )
            return False


class CameraSetupWizard(QWizard):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Camera Setup Wizard")
        self.settings = {}  # This dict will be populated by the pages
        self.setWizardStyle(QWizard.ModernStyle)
        # self.setOption(QWizard.HaveHelpButton, True) # If you add help texts

        # Add pages in logical order
        self.addPage(CameraScanPage())  # Page 0
        self.addPage(DefaultsPage())  # Page 1
        self.addPage(AdvancedSettingsPage())  # Page 2
        self.addPage(TestCapturePage())  # Page 3
        self.addPage(SummaryPage())  # Page 4

        # self.helpRequested.connect(self.showHelp) # Example for help

    # def showHelp(self):
    #     page_id = self.currentId()
    #     help_text = "Generic help for the wizard."
    #     if page_id == 0: help_text = "Scan for cameras..."
    #     # ... more specific help texts
    #     QMessageBox.information(self, "Help", help_text)
