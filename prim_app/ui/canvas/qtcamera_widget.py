# File: prim_app/ui/canvas/qtcamera_widget.py

from PyQt5.QtWidgets import QWidget
from PyQt5.QtGui import QPainter, QImage
from PyQt5.QtCore import Qt, pyqtSlot


class QtCameraWidget(QWidget):
    """
    A simple widget that displays incoming QImage frames from the camera thread.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_qimage = None

    @pyqtSlot(QImage, object)
    def _on_frame_ready(self, qimg: QImage, raw_buffer):
        """
        Slot to receive each new frame from SDKCameraThread.frame_ready.
        Simply store the QImage and trigger a repaint.
        """
        # Make a deep copy to ensure the data stays valid even if the thread recycles buffers
        self._current_qimage = qimg.copy()
        # Ask Qt to repaint this widget
        self.update()

    def clear_image(self):
        """
        Clear the displayed image (e.g. when stopping the camera).
        """
        self._current_qimage = None
        self.update()

    def paintEvent(self, event):
        """
        Called whenever the widget needs to be repainted. If we have a QImage,
        draw it scaled to fit while preserving aspect ratio. Otherwise, fill
        background with black.
        """
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.black)

        if self._current_qimage:
            # Scale the image to fit this widget, preserving aspect ratio
            scaled = self._current_qimage.scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            # Center the image
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawImage(x, y, scaled)

        painter.end()
