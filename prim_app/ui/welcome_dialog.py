# File: prim_app/ui/welcome_dialog.py

import os
import sys
import subprocess
from utils.path_helpers import resource_path
from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QCheckBox,
)


class WelcomeDialog(QDialog):
    """Simple welcome screen shown on first launch"""

    def __init__(self, parent=None, force_show: bool = False):
        super().__init__(parent)

        # Persistent setting
        self.settings = QSettings("YourCompany", "PRIMApp")
        self._skip = False
        if not force_show and not self.settings.value(
            "PRIMApp/ShowWelcome", True, type=bool
        ):
            self._skip = True
            self.close()
            return

        self.setWindowTitle("\U0001F44B Welcome to PRIMAcquisition")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumSize(500, 420)
        self.setStyleSheet(
            """
            QDialog {
                background-color: #2b2b2b;
                color: white;
                border-radius: 10px;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        intro = QLabel(
            "PRIMAcquisition lets you record synchronized <b>pressure data and video</b> for your experiments.<br>"
            "Follow these steps to get started quickly:"
        )
        layout.addWidget(intro)

        steps = [
            ("plug.svg", "Connect PRIM Device", "Select Arduino COM port and click Connect"),
            ("camera.svg", "Set Up Camera", "Choose camera & resolution then click Start Camera"),
            ("settings.svg", "Adjust Exposure/Gain", "Use controls to fine-tune camera settings"),
            ("sync.svg", "Zero PRIM", "Make sure pressure is at zero"),
            ("record.svg", "Start Recording", "Click Start Recording to begin acquisition"),
            ("stop.svg", "Stop Recording", "Click Stop Recording when finished"),
            ("export.svg", "Playback & Export", "Click Playback to review and export frames"),
        ]

        for icon, title, desc in steps:
            row = QHBoxLayout()
            icon_lbl = QLabel()
            icon_path = resource_path("ui", "icons", icon)
            icon_lbl.setPixmap(
                QPixmap(icon_path).scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            row.addWidget(icon_lbl)

            text_col = QVBoxLayout()
            title_lbl = QLabel(title)
            title_lbl.setStyleSheet("font-size: 11pt; font-weight: bold;")
            desc_lbl = QLabel(desc)
            desc_lbl.setWordWrap(True)
            desc_lbl.setStyleSheet("font-size: 9pt; color: #aaaaaa;")
            text_col.addWidget(title_lbl)
            text_col.addWidget(desc_lbl)
            row.addLayout(text_col)
            layout.addLayout(row)

        self.checkbox = QCheckBox("Don't show this again")
        self.checkbox.stateChanged.connect(self._toggle_show)
        layout.addWidget(self.checkbox)

        footer = QHBoxLayout()
        readme_btn = QPushButton("Read Full User Guide →")
        readme_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #3a7bd5;
                color: white;
                border-radius: 5px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #559de8;
            }
            """
        )
        readme_btn.clicked.connect(self._open_user_guide)
        footer.addWidget(readme_btn)
        footer.addStretch()
        start_btn = QPushButton("Start Using PRIMAcquisition")
        start_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #3a7bd5;
                color: white;
                border-radius: 5px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #559de8;
            }
            """
        )
        start_btn.clicked.connect(self.accept)
        footer.addWidget(start_btn)
        layout.addLayout(footer)

    def _toggle_show(self, state):
        self.settings.setValue("PRIMApp/ShowWelcome", state != Qt.Checked)

    def _open_user_guide(self):
        pdf_path = os.path.join(
            os.path.dirname(__file__), "docs", "PRIMAcquisition_UserGuide.pdf"
        )
        if os.path.exists(pdf_path):
            if sys.platform == "win32":
                os.startfile(pdf_path)
            elif sys.platform == "darwin":
                subprocess.call(["open", pdf_path])
            else:
                subprocess.call(["xdg-open", pdf_path])
