# File: prim_app/ui/welcome_dialog.py

import os
from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtGui import QIcon, QFont
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QCheckBox,
)


class WelcomeDialog(QDialog):
    """Single-sheet welcome dialog with a thin progress bar and step text."""

    def __init__(self, parent=None, force_show: bool = False):
        super().__init__(parent)

        # Persistent settings
        self.settings = QSettings("YourCompany", "PRIMApp")
        self._skip = False
        if not force_show and not self.settings.value(
            "PRIMApp/ShowWelcome", True, type=bool
        ):
            self._skip = True
            self.close()
            return

        # Step definitions: (title, description, icon_name)
        self.steps = [
            (
                "Connect PRIM Device",
                "Select your Arduino from the PRIM Device dropdown and click Connect PRIM Device. PRIM Device will show up as USB Serial Device (COM#)",
                "plug.svg",
            ),
            (
                "Configure Camera",
                "Choose your camera and resolution from the Select Device and Select Resolution dropdown menu. (At the moment only Imaging Source cameras are supported)",
                "settings.svg",
            ),
            (
                "Start Live Feed",
                "In the info panel click Start Camera and adjust the Exposure & Gain sliders in the Control panel.",
                "image.svg",
            ),
            (
                "Record Session",
                "Click Start Recording. Video and pressure data will sync automatically.",
                "record.svg",
            ),
            (
                "Finish & Reset",
                "Click Stop Recording, then Zero PRIM to reset the pressure baseline. Files will be saved to the PRIMAcquisition folder in documents. Destination can be changed from the File menu",
                "reset_zoom.svg",
            ),
        ]
        self.current = 0

        # Window setup
        self.setWindowTitle("Welcome to PRIMAcquisition")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumSize(480, 360)
        self.setStyleSheet(
            """
            QDialog { background-color: #2b2b2b; }
            QLabel { color: #ffffff; }
            QPushButton { background: #444444; color: #ffffff; padding: 6px 12px; border-radius: 4px; }
            QPushButton:disabled { background: #555555; color: #888888; }
            QProgressBar { background: #444444; border: none; border-radius: 3px; height: 6px; }
            QProgressBar::chunk { background: #0078d7; border-radius: 3px; }
            QCheckBox { color: #cccccc; }
            """
        )

        # Layout
        layout = QVBoxLayout(self)

        # Stepper bar
        self.stepper = QProgressBar()
        self.stepper.setRange(0, len(self.steps) - 1)
        self.stepper.setTextVisible(False)
        layout.addWidget(self.stepper)

        # Icon
        self.icon_lbl = QLabel(alignment=Qt.AlignCenter)
        self.icon_lbl.setFixedHeight(80)
        layout.addWidget(self.icon_lbl)

        # Title
        self.title_lbl = QLabel(alignment=Qt.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        self.title_lbl.setFont(title_font)
        layout.addWidget(self.title_lbl)

        # Description
        self.desc_lbl = QLabel(alignment=Qt.AlignCenter)
        self.desc_lbl.setWordWrap(True)
        layout.addWidget(self.desc_lbl)

        # Navigation buttons
        btn_layout = QHBoxLayout()
        self.back_btn = QPushButton("Back")
        self.back_btn.clicked.connect(self._prev)
        btn_layout.addWidget(self.back_btn)
        btn_layout.addStretch()
        self.next_btn = QPushButton("Next")
        self.next_btn.clicked.connect(self._next)
        btn_layout.addWidget(self.next_btn)
        layout.addLayout(btn_layout)

        # "Don't show again" toggle
        self.checkbox = QCheckBox("Don't show again")
        self.checkbox.stateChanged.connect(self._toggle_show)
        layout.addWidget(self.checkbox, alignment=Qt.AlignCenter)

        self._update_step()

        # Center the dialog on the screen that contains the parent window
        self.adjustSize()
        screen = (
            self.parent().windowHandle().screen()
            if self.parent() and self.parent().windowHandle()
            else QApplication.primaryScreen()
        )
        if screen:
            geo = self.frameGeometry()
            geo.moveCenter(screen.availableGeometry().center())
            self.move(geo.topLeft())

    # ------------------------------------------------------------------
    def _icon(self, name: str) -> QIcon:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(base_dir, "icons", name)
        return QIcon(icon_path) if os.path.exists(icon_path) else QIcon()

    def _update_step(self):
        """Refresh UI elements based on current step."""
        title, desc, icon_name = self.steps[self.current]
        self.stepper.setValue(self.current)
        icon = self._icon(icon_name)
        if not icon.isNull():
            self.icon_lbl.setPixmap(icon.pixmap(64, 64))
        else:
            self.icon_lbl.clear()
        self.title_lbl.setText(title)
        self.desc_lbl.setText(desc)
        self.back_btn.setEnabled(self.current > 0)
        self.next_btn.setText(
            "Finish" if self.current == len(self.steps) - 1 else "Next"
        )

    def _next(self):
        if self.current < len(self.steps) - 1:
            self.current += 1
            self._update_step()
        else:
            self.accept()

    def _prev(self):
        if self.current > 0:
            self.current -= 1
            self._update_step()

    def _toggle_show(self, state):
        # Checked = hide future dialogs
        self.settings.setValue("PRIMApp/ShowWelcome", state != Qt.Checked)
