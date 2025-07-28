# File: prim_app/ui/welcome_dialog.py

import os
from utils.path_helpers import resource_path
from PyQt5.QtCore import Qt, QSettings, QUrl
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
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

        layout = QVBoxLayout(self)

        intro = QLabel(
            "PRIMAcquisition lets you record synchronized <b>pressure data and video</b> for your experiments.<br>"
            "Follow these steps to get started quickly:"
        )
    
        for num, emoji, title, desc in steps:
            row = QHBoxLayout()
            icon_lbl = QLabel(f"{num} {emoji}")
            icon_lbl.setFixedWidth(60)
            row.addWidget(icon_lbl, alignment=Qt.AlignTop)
            text = QLabel(f"<b>{title}</b><br>{desc}")
            text.setWordWrap(True)
            row.addWidget(text)
            layout.addLayout(row)

        self.checkbox = QCheckBox("Don't show this again")
        self.checkbox.stateChanged.connect(self._toggle_show)
        layout.addWidget(self.checkbox)

        footer = QHBoxLayout()
        readme_btn = QPushButton("Read Full User Guide →")
        readme_btn.clicked.connect(self._open_readme)
        footer.addWidget(readme_btn)
        footer.addStretch()
        start_btn = QPushButton("Start Using PRIMAcquisition")
        start_btn.clicked.connect(self.accept)
        footer.addWidget(start_btn)
        layout.addLayout(footer)

    def _toggle_show(self, state):
        self.settings.setValue("PRIMApp/ShowWelcome", state != Qt.Checked)

    def _open_readme(self):
        path = os.path.abspath(os.path.join(resource_path("..", "README.md")))
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
