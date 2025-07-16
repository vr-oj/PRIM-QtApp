from abc import ABC, abstractmethod
from PyQt5.QtCore import QObject, pyqtSignal, QMetaObject, Qt
from PyQt5.QtGui import QImage


class ICameraController(QObject, ABC):
    """Abstract camera controller interface."""

    frame_ready = pyqtSignal(int, QImage, object)
    """Emitted when a frame is available: (master_ts_ns, QImage, raw_buffer)."""

    @abstractmethod
    def arm_trigger(self):
        pass

    @abstractmethod
    def grab_frame(self):
        pass

    @abstractmethod
    def disarm_trigger(self):
        pass


from threads.sdk_camera_thread import SDKCameraThread
from utils.sync_manager import SyncManager


class IC4CameraController(ICameraController):
    """Wrap :class:`SDKCameraThread` to provide :class:`ICameraController` API."""

    def __init__(self, thread: SDKCameraThread, parent=None):
        super().__init__(parent)
        self._thread = thread
        self._thread.frame_ready.connect(self._relay_frame)

    def arm_trigger(self):
        if not self._thread.isRunning():
            self._thread.start()

    def grab_frame(self):
        if self._thread.isRunning():
            QMetaObject.invokeMethod(self._thread, "snap", Qt.QueuedConnection)

    def disarm_trigger(self):
        if self._thread.isRunning():
            self._thread.stop()
            self._thread.wait(1000)

    def _relay_frame(self, qimg: QImage, raw: object):
        ts = SyncManager.now()
        self.frame_ready.emit(ts, qimg, raw)
