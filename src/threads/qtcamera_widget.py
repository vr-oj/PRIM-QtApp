from PyQt5.QtWidgets       import QWidget, QVBoxLayout
from PyQt5.QtMultimedia    import QCamera, QCameraInfo, QVideoProbe, QVideoFrame
from PyQt5.QtMultimediaWidgets import QCameraViewfinder
from PyQt5.QtCore          import pyqtSignal, Qt
from PyQt5.QtGui           import QImage

class QtCameraWidget(QWidget):
    # exactly the same signal signature your VideoThread used:
    frame_ready = pyqtSignal(QImage, object)

    def __init__(self, parent=None):
        super().__init__(parent)

        # 1) create a viewfinder and lay it out
        self.viewfinder = QCameraViewfinder(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self.viewfinder)

        # 2) pick the default camera
        camera_info = QCameraInfo.defaultCamera()
        self.camera = QCamera(camera_info)
        self.camera.setViewfinder(self.viewfinder)

        # 3) set up a probe so we get raw video frames
        self.probe = QVideoProbe(self)
        self.probe.videoFrameProbed.connect(self._on_frame)
        self.probe.setSource(self.camera)

        # 4) start it
        self.camera.start()

    def _on_frame(self, frame: QVideoFrame):
        """Called in GUI thread on each new frame."""
        if not frame.isValid():
            return

        frame.map(QVideoFrame.ReadOnly)

        img = QImage(
            frame.bits(),
            frame.width(),
            frame.height(),
            frame.bytesPerLine(),
            # convert the Qt pixel format to a QImage::Format:
            QVideoFrame.imageFormatFromPixelFormat(frame.pixelFormat())
        ).copy()  # copy because the underlying buffer will be unmapped next

        frame.unmap()

        # emit exactly what your existing code expects:
        self.frame_ready.emit(img, None)
