import logging

from PyQt5.QtWidgets import (
    QGroupBox,
    QFormLayout,
    QLabel,
    QDoubleSpinBox,
    QPushButton,
)
from PyQt5.QtCore import pyqtSignal

log = logging.getLogger(__name__)


class PumpControlPanel(QGroupBox):
    """Simple UI panel for syringe pump info."""

    set_rate_requested = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__("Syringe Pump", parent)

        layout = QFormLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(4)

        self.volume_lbl = QLabel("0")
        layout.addRow("Volume (uL):", self.volume_lbl)

        self.current_rate_lbl = QLabel("0")
        layout.addRow("Current Rate:", self.current_rate_lbl)

        self.target_rate_spin = QDoubleSpinBox()
        self.target_rate_spin.setDecimals(2)
        self.target_rate_spin.setRange(0, 1000)
        layout.addRow("Target Rate:", self.target_rate_spin)

        self.set_rate_btn = QPushButton("Set Rate")
        self.set_rate_btn.clicked.connect(self._emit_rate)
        layout.addRow(self.set_rate_btn)

    def _emit_rate(self):
        self.set_rate_requested.emit(self.target_rate_spin.value())

