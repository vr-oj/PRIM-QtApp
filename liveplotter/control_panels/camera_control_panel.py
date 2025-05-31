# camera_control_panel.py

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QComboBox,
    QHBoxLayout,
    QPushButton,
)
from PyQt5.QtCore import pyqtSignal
import logging

log = logging.getLogger(__name__)


class CameraControlPanel(QWidget):
    device_selected = pyqtSignal(str)
    resolution_selected = pyqtSignal(str)
    trigger_start_stream = pyqtSignal()
    trigger_stop_stream = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.device_selector = QComboBox()
        self.res_selector = QComboBox()
        self.start_button = QPushButton("Start")
        self.stop_button = QPushButton("Stop")

        layout = QVBoxLayout()
        layout.setSpacing(4)
        layout.setContentsMargins(4, 4, 4, 4)

        device_layout = QHBoxLayout()
        device_layout.addWidget(QLabel("Camera:"))
        device_layout.addWidget(self.device_selector)
        layout.addLayout(device_layout)

        res_layout = QHBoxLayout()
        res_layout.addWidget(QLabel("Resolution:"))
        res_layout.addWidget(self.res_selector)
        layout.addLayout(res_layout)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.stop_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

        self.device_selector.currentTextChanged.connect(self.device_selected.emit)
        self.res_selector.currentTextChanged.connect(self.resolution_selected.emit)
        self.start_button.clicked.connect(self.trigger_start_stream.emit)
        self.stop_button.clicked.connect(self.trigger_stop_stream.emit)

    def set_devices(self, devices: list[str]):
        self.device_selector.clear()
        self.device_selector.addItems(devices)
        log.debug(f"Device list updated: {devices}")

    def set_resolutions(self, resolutions: list[str]):
        self.res_selector.clear()
        self.res_selector.addItems(resolutions)
        log.debug(f"Resolution list updated: {resolutions}")
