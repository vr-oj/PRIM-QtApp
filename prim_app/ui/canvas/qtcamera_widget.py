# File: prim_app/ui/canvas/qtcamera_widget.py
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QPixmap, QImage

class QtCameraWidget(QWidget):
    """
    Simplest camera widget: a QLabel to show frames, and no button here.
    MainWindow will drive start/stop via SDKCameraThread.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayout(QVBoxLayout())

        # Use a single QVBoxLayout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Inside QtCameraWidget.__init__ or setup:
        self._label = QLabel("Camera Off", self)
        self._label.setAlignment(Qt.AlignCenter)
        # Fix the label’s “logical” size (you can adjust if you want a different preview size).
        self._label.setFixedSize(640, 480)
        layout.addWidget(self._label)

    @pyqtSlot(QImage, object)
    def _on_frame_ready(self, image: QImage, raw):
         """
         Receives QImage + numpy array from SDKCameraThread.
         Converts QImage → QPixmap and displays it.
         """
         pix = QPixmap.fromImage(image)
         self._label.setPixmap(pix.scaled(
            self._label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
         ))
    @pyqtSlot(str, str)
    def _on_error(self, msg: str, code: str):
         """
         If anything goes wrong, show the error text in the QLabel.
         """
         self._label.setText(f"❗ {msg}")

    def _toggle_camera(self):
         """
         Start or stop the camera thread on button click.
         """
         # (Disabled: MainWindow now toggles the camera thread instead)
         pass

    def update_image(self, image: QImage):
        """
        Public slot for MainWindow (or anyone) to push a new QImage into this viewfinder.
        """
        pix = QPixmap.fromImage(image)
        self._label.setPixmap(pix.scaled(self._label.size(), Qt.KeepAspectRatio))

    def clear_image(self):
        """
        Public helper: clear the pixmap and show “Camera Off” again.
        """
        self._label.clear()
        self._label.setText("Camera Off")