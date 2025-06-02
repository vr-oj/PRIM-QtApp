# prim_app/ui/widgets/qt_camera_widget.py

from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout, QSizePolicy
from PyQt5.QtCore import Qt, QSize, pyqtSlot
from PyQt5.QtGui import QPixmap, QImage


class QtCameraWidget(QWidget):
    """
    A simple “viewfinder” widget that displays each incoming QImage
    onto a QLabel. Before frames arrive, it shows “No Camera Selected” text.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # Keep the last QImage around so that we can re‐paint on resize.
        self._last_qimg = None

        # ─── Viewfinder Label ──────────────────────────────────────────────────
        # This QLabel will show “No Camera Selected” initially, then
        # be replaced by each incoming frame (converted to QPixmap).
        self.viewfinder = QLabel("No Camera Selected", self)
        self.viewfinder.setAlignment(Qt.AlignCenter)
        self.viewfinder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Make the background black to mimic a camera viewfinder:
        self.viewfinder.setStyleSheet("background-color: black; color: white;")

        # ─── Layout ─────────────────────────────────────────────────────────────
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.viewfinder)

    @pyqtSlot(QImage)
    def update_image(self, qimg: QImage):
        """
        Slot for incoming frames (as QImage). Convert to QPixmap,
        scale to fit the label’s current size, and display.
        """
        self._last_qimg = qimg

        if qimg is None or qimg.isNull():
            # If invalid, revert to text placeholder
            self.viewfinder.setText("No Camera Selected")
            self.viewfinder.setPixmap(QPixmap())
            return

        # Scale the QImage to the QLabel’s size, preserving aspect ratio
        target_size = self.viewfinder.size()
        scaled = qimg.scaled(target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pix = QPixmap.fromImage(scaled)
        self.viewfinder.setPixmap(pix)

    def clear_image(self):
        """
        Clear the viewfinder (e.g. when camera stops or on error).
        """
        self._last_qimg = None
        self.viewfinder.clear()
        self.viewfinder.setText("No Camera Selected")

    def resizeEvent(self, event):
        """
        Whenever the widget is resized, repaint the last QImage (if any).
        """
        super().resizeEvent(event)
        if self._last_qimg is not None and not self._last_qimg.isNull():
            target_size = self.viewfinder.size()
            scaled = self._last_qimg.scaled(
                target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            pix = QPixmap.fromImage(scaled)
            self.viewfinder.setPixmap(pix)
        else:
            # If there’s no frame yet, just keep the placeholder text
            self.viewfinder.setText("No Camera Selected")
