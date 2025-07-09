# File: prim_app/ui/welcome_dialog.py

import os
from PyQt5.QtCore import Qt, QSettings, QPropertyAnimation
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QStackedWidget, QCheckBox, QFrame
)


class WelcomeDialog(QDialog):
    """Step-by-step welcome dialog with persistence via ``QSettings``."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to PRIM Live Recorder")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumSize(500, 400)
        self.setStyleSheet(
            """
            QDialog { background-color: #2b2b2b; }
            QFrame#stepFrame { background: #3c3f41; border-radius: 8px; padding: 16px; }
            QLabel#title { font-size: 18px; font-weight: bold; color: #ffffff; }
            QLabel#desc { font-size: 14px; color: #d0d0d0; }
            QPushButton { padding: 8px 16px; border-radius: 4px; background: #4a4a4a; color: #ffffff; }
            QPushButton#next { background-color: #0078d7; }
            QPushButton#back { background: none; color: #bbbbbb; }
            QCheckBox { color: #cccccc; }
            """
        )

        # QSettings for persistence
        self.settings = QSettings("YourCompany", "PRIMApp")
        if not self.settings.value("PRIMApp/ShowWelcome", True, type=bool):
            self._skip = True
            self.close()
            return
        self._skip = False

        layout = QVBoxLayout(self)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        steps = [
            ("Connect PRIM Device", "Select your Arduino from the PRIM Device dropdown and click Connect.", "plug.svg"),
            ("Configure Camera", "Choose your camera or load a µManager config (.rcp).", "settings.svg"),
            ("Start Live Feed", "Click Start Camera and adjust Exposure/Gain sliders.", "image.svg"),
            ("Record Session", "Click Start Recording. Video and pressure data will sync.", "record.svg"),
            ("Finish & Reset", "Click Stop Recording, then Zero PRIM to reset baseline.", "reset_zoom.svg"),
        ]
        for title, desc, icon_name in steps:
            self.stack.addWidget(self._make_page(title, desc, icon_name))

        btn_layout = QHBoxLayout()
        self.back_btn = QPushButton("Back")
        self.back_btn.setObjectName("back")
        self.back_btn.clicked.connect(self._prev)
        self.next_btn = QPushButton("Next")
        self.next_btn.setObjectName("next")
        self.next_btn.clicked.connect(self._next)
        btn_layout.addWidget(self.back_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.next_btn)
        layout.addLayout(btn_layout)

        self.checkbox = QCheckBox("Don't show this again")
        self.checkbox.stateChanged.connect(self._toggle_show)
        layout.addWidget(self.checkbox, alignment=Qt.AlignLeft)

        self._update_buttons()

    # ------------------------------------------------------------------
    def _icon(self, name: str) -> QIcon:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(base_dir, "icons", name)
        return QIcon(icon_path) if os.path.exists(icon_path) else QIcon()

    def _make_page(self, title, desc, icon_name):
        frame = QFrame()
        frame.setObjectName("stepFrame")
        v = QVBoxLayout(frame)
        lbl_icon = QLabel()
        icon = self._icon(icon_name)
        if not icon.isNull():
            lbl_icon.setPixmap(icon.pixmap(48, 48))
        lbl_icon.setAlignment(Qt.AlignCenter)
        lbl_title = QLabel(title)
        lbl_title.setObjectName("title")
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_desc = QLabel(desc)
        lbl_desc.setObjectName("desc")
        lbl_desc.setWordWrap(True)
        lbl_desc.setAlignment(Qt.AlignCenter)
        v.addWidget(lbl_icon)
        v.addSpacing(8)
        v.addWidget(lbl_title)
        v.addSpacing(4)
        v.addWidget(lbl_desc)
        v.addStretch()
        return frame

    def _next(self):
        idx = self.stack.currentIndex()
        if idx < self.stack.count() - 1:
            self._animate(idx, idx + 1)
            self.stack.setCurrentIndex(idx + 1)
        else:
            self.accept()
        self._update_buttons()

    def _prev(self):
        idx = self.stack.currentIndex()
        if idx > 0:
            self._animate(idx, idx - 1)
            self.stack.setCurrentIndex(idx - 1)
        self._update_buttons()

    def _update_buttons(self):
        idx = self.stack.currentIndex()
        self.back_btn.setEnabled(idx > 0)
        self.next_btn.setText("Finish" if idx == self.stack.count() - 1 else "Next")

    def _toggle_show(self, state):
        self.settings.setValue("PRIMApp/ShowWelcome", state != Qt.Checked)

    def _animate(self, from_idx, to_idx):
        old = self.stack.widget(from_idx)
        new = self.stack.widget(to_idx)
        for w, start, end in ((old, 1.0, 0.0), (new, 0.0, 1.0)):
            anim = QPropertyAnimation(w, b"windowOpacity", self)
            anim.setDuration(200)
            anim.setStartValue(start)
            anim.setEndValue(end)
            anim.start()


