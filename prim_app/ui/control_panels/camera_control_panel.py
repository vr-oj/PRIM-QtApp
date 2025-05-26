# PRIM-QTAPP/prim_app/ui/control_panels/camera_control_panel.py
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QComboBox,
    QDoubleSpinBox,
    QSlider,
    QCheckBox,
    QHBoxLayout,
    QPushButton,
)
from PyQt5.QtCore import pyqtSignal, Qt


class CameraControlPanel(QWidget):
    """
    Panel for live camera settings: resolution, pixel format, auto exposure,
    exposure time, gain, and frame rate.
    """

    resolution_changed = pyqtSignal(str)
    pixel_format_changed = pyqtSignal(str)
    auto_exposure_toggled = pyqtSignal(bool)
    exposure_changed = pyqtSignal(float)
    gain_changed = pyqtSignal(float)
    fps_changed = pyqtSignal(float)
    start_stream = pyqtSignal()
    stop_stream = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(10)

        # Title
        title = QLabel("Camera Settings")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Resolution dropdown
        layout.addWidget(QLabel("Resolution:"))
        self.res_combo = QComboBox()
        self.res_combo.currentTextChanged.connect(self.resolution_changed)
        layout.addWidget(self.res_combo)

        # Pixel format dropdown
        layout.addWidget(QLabel("Pixel Format:"))
        self.pix_combo = QComboBox()
        self.pix_combo.currentTextChanged.connect(self.pixel_format_changed)
        layout.addWidget(self.pix_combo)

        # Auto Exposure
        self.auto_exp_cb = QCheckBox("Auto Exposure")
        self.auto_exp_cb.stateChanged.connect(
            lambda state: self.auto_exposure_toggled.emit(state == Qt.Checked)
        )
        layout.addWidget(self.auto_exp_cb)

        # Manual Exposure time
        exp_layout = QHBoxLayout()
        exp_layout.addWidget(QLabel("Exposure (ms):"))
        self.exp_spin = QDoubleSpinBox()
        self.exp_spin.setRange(0.1, 60000)
        self.exp_spin.setSingleStep(0.1)
        self.exp_spin.valueChanged.connect(self.exposure_changed)
        exp_layout.addWidget(self.exp_spin)
        layout.addLayout(exp_layout)

        # Gain slider
        gain_layout = QVBoxLayout()
        gain_label = QLabel("Gain:")
        gain_layout.addWidget(gain_label)
        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setRange(0, 100)
        self.gain_slider.setTickInterval(5)
        self.gain_slider.setTickPosition(QSlider.TicksBelow)
        self.gain_slider.valueChanged.connect(
            lambda v: self.gain_changed.emit(float(v))
        )
        gain_layout.addWidget(self.gain_slider)
        layout.addLayout(gain_layout)

        # Frame rate
        layout.addWidget(QLabel("Frame Rate (FPS):"))
        self.fps_spin = QDoubleSpinBox()
        self.fps_spin.setRange(0.1, 240.0)
        self.fps_spin.setSingleStep(0.1)
        self.fps_spin.valueChanged.connect(self.fps_changed)
        layout.addWidget(self.fps_spin)

        # Start/Stop Live buttons
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Live")
        self.start_btn.clicked.connect(self.start_stream)
        self.stop_btn = QPushButton("Stop Live")
        self.stop_btn.clicked.connect(self.stop_stream)
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        layout.addLayout(btn_layout)

        layout.addStretch()
