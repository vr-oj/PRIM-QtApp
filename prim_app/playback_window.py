import sys
import os
import csv
import numpy as np
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QSpinBox,
    QSlider,
)
from tifffile import TiffFile, imwrite
from PIL import Image, ImageDraw, ImageFont


class PlaybackWindow(QMainWindow):
    """Display a TIFF stack with pressure overlay and playback controls."""

    def __init__(self, tiff_path=None, csv_path=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Playback with Overlay")
        self.resize(800, 600)

        self.frames = []
        self.pressures = []
        self.current_frame = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next_frame)

        # ─── Widgets ──────────────────────────────────────────────────────
        self.label = QLabel(alignment=Qt.AlignCenter)
        self.play_btn = QPushButton("\u25B6 Play")
        self.play_btn.setCheckable(True)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)

        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 1000)
        self.fps_spin.setValue(10)
        self.fps_spin.valueChanged.connect(self.update_fps)

        self.export_btn = QPushButton("💾 Export Overlay TIFF")

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(4, 4, 4, 4)
        btn_layout.setSpacing(6)
        btn_layout.addWidget(self.play_btn)
        btn_layout.addWidget(self.slider, stretch=1)
        btn_layout.addWidget(QLabel("FPS:"))
        btn_layout.addWidget(self.fps_spin)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.export_btn)

        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)
        layout.addWidget(self.label, stretch=1)
        layout.addLayout(btn_layout)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # ─── Signals ──────────────────────────────────────────────────────
        self.play_btn.clicked.connect(self._toggle_play)
        self.slider.valueChanged.connect(self.set_frame)
        self.export_btn.clicked.connect(self.export_overlay)

        if tiff_path and csv_path:
            self.load_files(tiff_path, csv_path)
        else:
            self.pick_files()

    # ─── File Loading ─────────────────────────────────────────────────────
    def pick_files(self):
        tiff, _ = QFileDialog.getOpenFileName(
            self, "Select TIFF", "", "TIFF files (*.tif *.tiff)"
        )
        if not tiff:
            return
        csv_path, _ = QFileDialog.getOpenFileName(
            self, "Select CSV", "", "CSV files (*.csv)"
        )
        if not csv_path:
            return
        self.load_files(tiff, csv_path)

    def load_files(self, tiff_path, csv_path):
        self.statusBar().showMessage("Loading files...")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            with TiffFile(tiff_path) as tif:
                self.frames = [page.asarray() for page in tif.pages]
        except Exception:
            self.frames = []

        try:
            with open(csv_path, "r", newline="") as f:
                reader = csv.DictReader(f)
                self.pressures = [float(row.get("pressure", 0)) for row in reader]
        except Exception:
            self.pressures = []

        QApplication.restoreOverrideCursor()
        self.statusBar().clearMessage()

        self.current_frame = 0
        self.slider.setEnabled(bool(self.frames))
        self.show_frame()

    # ─── Overlay Helpers ─────────────────────────────────────────────────-
    def overlay_frame(self, frame, pressure):
        img = Image.fromarray(frame)
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("Arial.ttf", 120)
        except Exception:
            font = ImageFont.load_default()
        draw.text(
            (10, 20),
            f"{pressure:.2f} mmHg",
            fill=255,
            font=font,
            stroke_width=2,
            stroke_fill=0,
        )
        return np.array(img)

    def show_frame(self):
        if not self.frames:
            return
        frame = self.frames[self.current_frame]
        pressure = self.pressures[min(self.current_frame, len(self.pressures) - 1)]
        overlaid = self.overlay_frame(frame, pressure)

        h, w = overlaid.shape
        qimg = QImage(overlaid.data, w, h, overlaid.strides[0], QImage.Format_Grayscale8)
        pix = QPixmap.fromImage(qimg).scaled(
            self.label.width(), self.label.height(), Qt.KeepAspectRatio
        )
        self.label.setPixmap(pix)
        if self.slider.maximum() != len(self.frames) - 1:
            self.slider.setRange(0, max(0, len(self.frames) - 1))
        self.slider.blockSignals(True)
        self.slider.setValue(self.current_frame)
        self.slider.blockSignals(False)

    # ─── Controls ─────────────────────────────────────────────────────────
    def _toggle_play(self, checked):
        if checked:
            self.play_btn.setText("\u23F8 Pause")
            self.timer.start(int(1000 / self.fps_spin.value()))
        else:
            self.play_btn.setText("\u25B6 Play")
            self.timer.stop()

    def next_frame(self):
        if not self.frames:
            return
        self.current_frame = (self.current_frame + 1) % len(self.frames)
        self.show_frame()

    def set_frame(self, idx):
        if not self.frames:
            return
        self.current_frame = max(0, min(idx, len(self.frames) - 1))
        self.show_frame()

    def update_fps(self):
        if self.timer.isActive():
            self.timer.setInterval(int(1000 / self.fps_spin.value()))

    def export_overlay(self):
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save Overlay TIFF", "", "TIFF files (*.tif *.tiff)"
        )
        if not out_path:
            return
        self.statusBar().showMessage("Exporting overlay...")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        overlaid_frames = [
            self.overlay_frame(f, p) for f, p in zip(self.frames, self.pressures)
        ]
        imwrite(out_path, np.array(overlaid_frames), photometric="minisblack")
        QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(f"Saved: {os.path.basename(out_path)}", 3000)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = PlaybackWindow()
    win.show()
    sys.exit(app.exec_())
