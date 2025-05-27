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
from utils.app_settings import load_app_setting, save_settings, SETTING_CTI_PATH

module_log = logging.getLogger(__name__)

# Set and verify CTI path
cti_path = load_app_setting(SETTING_CTI_PATH)
if cti_path:
    os.environ["GENICAM_GENTL64_PATH"] = os.path.dirname(cti_path)
else:
    QMessageBox.warning(None, "CTI Not Configured", "No CTI path found in settings.")

# Initialize IC4 library once
try:
    ic4.Library.init()
except RuntimeError:
    # already initialized
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
        btn = QPushButton("Scan for Cameras")
        btn.clicked.connect(self.scan)
        layout.addWidget(btn)
        layout.addWidget(QLabel("Available Cameras:"))
        self.combo = QComboBox()
        layout.addWidget(self.combo)

    def scan(self):
        try:
            devices = ic4.Device.enumerate()
        except ic4.IC4Exception as e:
            QMessageBox.critical(self, "Scan Error", f"{e.code}: {e.message}")
            return
        self.combo.clear()
        if not devices:
            self.combo.addItem("No cameras found")
            self.combo.setEnabled(False)
        else:
            self.combo.setEnabled(True)
            for dev in devices:
                self.combo.addItem(f"{dev.model_name} (SN: {dev.serial_number})", dev)
        self.completeChanged.emit()

    def isComplete(self):
        return self.combo.currentIndex() >= 0 and self.combo.isEnabled()

    def validatePage(self):
        dev = self.combo.currentData()
        if not dev:
            QMessageBox.warning(self, "Select Camera", "Please pick a camera.")
            return False
        self.wizard().settings["device_info"] = dev
        return True


class DefaultsPage(QWizardPage):
    """Page 2: Basic GenICam defaults"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Default Settings")
        layout = QFormLayout(self)
        self.pix = QComboBox()
        self.exp = QDoubleSpinBox()
        self.exp.setSuffix(" µs")
        self.gain = QDoubleSpinBox()
        self.gain.setSuffix(" dB")
        self.fps = QDoubleSpinBox()
        self.fps.setSuffix(" FPS")
        self.wd = QSpinBox()
        self.ht = QSpinBox()
        for label, w in [
            ("Pixel Format:", self.pix),
            ("Exposure Time:", self.exp),
            ("Gain:", self.gain),
            ("Frame Rate:", self.fps),
            ("Width:", self.wd),
            ("Height:", self.ht),
        ]:
            layout.addRow(label, w)

    def initializePage(self):
        dev = self.wizard().settings.get("device_info")
        grabber = ic4.Grabber(dev)
        grabber.device_open()
        nm = grabber.node_map
        # PF
        pf = nm["PixelFormat"]
        self.pix.clear()
        self.pix.addItems([str(o) for o in pf.options])
        self.pix.setCurrentText(str(pf.value))
        # Num
        for name, widget in [
            ("ExposureTime", self.exp),
            ("Gain", self.gain),
            ("AcquisitionFrameRate", self.fps),
            ("Width", self.wd),
            ("Height", self.ht),
        ]:
            node = nm[name]
            widget.setRange(node.min, node.max)
            widget.setValue(node.value)
        grabber.close_device()

    def validatePage(self):
        self.wizard().settings["defaults"] = {
            "PixelFormat": self.pix.currentText(),
            "ExposureTime": self.exp.value(),
            "Gain": self.gain.value(),
            "AcquisitionFrameRate": self.fps.value(),
            "Width": self.wd.value(),
            "Height": self.ht.value(),
        }
        return True


class AdvancedPage(QWizardPage):
    """Page 3: Advanced GenICam nodes"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Advanced Settings")
        layout = QVBoxLayout(self)
        self.scroll = QScrollArea()
        self.container = QWidget()
        self.form = QFormLayout(self.container)
        self.scroll.setWidget(self.container)
        self.scroll.setWidgetResizable(True)
        layout.addWidget(self.scroll)
        self.widgets = {}

    def initializePage(self):
        for i in reversed(range(self.form.count())):
            w = self.form.itemAt(i).widget()
            w and w.deleteLater()
        self.widgets.clear()
        dev = self.wizard().settings["device_info"]
        grabber = ic4.Grabber(dev)
        grabber.device_open()
        nm = grabber.node_map
        defaults = set(self.wizard().settings["defaults"].keys())
        for name, node in nm.items():
            if name in defaults:
                continue
            w = None
            if node.type == "IEnumeration":
                w = QComboBox()
                w.addItems([str(o) for o in node.options])
                w.setCurrentText(str(node.value))
            elif node.type == "IInteger":
                w = QSpinBox()
                w.setRange(node.min, node.max)
                w.setValue(node.value)
            elif node.type == "IFloat":
                w = QDoubleSpinBox()
                w.setRange(node.min, node.max)
                w.setValue(node.value)
            elif node.type == "IBoolean":
                w = QCheckBox()
                w.setChecked(bool(node.value))
            if w:
                self.form.addRow(name + ":", w)
                self.widgets[name] = w
        grabber.close_device()

    def validatePage(self):
        adv = {}
        for name, w in self.widgets.items():
            if isinstance(w, QComboBox):
                adv[name] = w.currentText()
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                adv[name] = w.value()
            elif isinstance(w, QCheckBox):
                adv[name] = w.isChecked()
        self.wizard().settings["advanced"] = adv
        return True


class TestPage(QWizardPage):
    """Page 4: Test acquisition"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Test Capture")
        layout = QVBoxLayout(self)
        self.lbl = QLabel("Press Test to grab one frame")
        self.btn = QPushButton("Test")
        self.btn.clicked.connect(self.test)
        layout.addWidget(self.lbl)
        layout.addWidget(self.btn)
        self.ok = False

    def test(self):
        self.btn.setEnabled(False)
        self.lbl.setText("Grabbing…")
        QApplication.processEvents()
        dev = self.wizard().settings["device_info"]
        grabber = ic4.Grabber(dev)
        sink = ic4.QueueSink()
        ln = ic4.QueueSinkListener()
        sink.attach(ln)
        grabber.stream_setup(sink)
        try:
            grabber.acquisition_start()
            frame = ln.get(timeout_ms=2000)
            grabber.acquisition_stop()
            grabber.close_device()
            self.lbl.setText(f"Got {frame.width}×{frame.height}")
            self.ok = True
        except ic4.IC4Exception as e:
            QMessageBox.critical(self, "Error", f"{e.code}: {e.message}")
            self.ok = False
        self.btn.setEnabled(True)
        self.completeChanged.emit()

    def isComplete(self):
        return self.ok

    def validatePage(self):
        return True


class SummaryPage(QWizardPage):
    """Page 5: Save profile"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Save Profile")
        fl = QFormLayout(self)
        self.name = QLineEdit()
        fl.addRow("Profile Name:", self.name)

    def initializePage(self):
        di = self.wizard().settings["device_info"]
        nm = f"{di.model_name}_{di.serial_number}".replace(" ", "_")
        self.name.setText(nm + "_profile")

    def validatePage(self):
        n = self.name.text().strip()
        if not n:
            QMessageBox.warning(self, "Name?", """Enter name""")
            return False
        s = self.wizard().settings
        prof = {
            "name": n,
            "cti": cti_path,
            "model": s["device_info"].model_name,
            "serial": s["device_info"].serial_number,
            "defaults": s.get("defaults", {}),
            "advanced": s.get("advanced", {}),
        }
        os.makedirs(CAMERA_PROFILES_DIR, exist_ok=True)
        p = os.path.join(CAMERA_PROFILES_DIR, f"{n}.json")
        with open(p, "w") as f:
            json.dump(prof, f, indent=2)
        save_settings({SETTING_CTI_PATH: cti_path})
        QMessageBox.information(self, "Saved", f"{p}")
        return True


class CameraSetupWizard(QWizard):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Camera Setup Wizard")
        self.settings = {}
        self.addPage(CameraScanPage())
        self.addPage(DefaultsPage())
        self.addPage(AdvancedPage())
        self.addPage(TestPage())
        self.addPage(SummaryPage())


if __name__ == "__main__":
    app = QApplication([])
    wiz = CameraSetupWizard()
    wiz.exec_()
