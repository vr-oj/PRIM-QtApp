import time
from typing import Callable
from PyQt5.QtCore import QObject, QTimer


class SyncManager(QObject):
    """Singleton providing a master timestamp clock and periodic tick timer."""

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, parent=None):
        if getattr(self, "_initialized", False):
            return
        super().__init__(parent)
        self._timer = QTimer(self)
        self._callback = None
        self._initialized = True

    @staticmethod
    def now() -> int:
        """Return the current master timestamp in nanoseconds."""
        return time.perf_counter_ns()

    def start(self, period_ms: float, callback: Callable):
        """Start the periodic tick timer."""
        self.stop()
        self._callback = callback
        if callback:
            self._timer.timeout.connect(callback)
        self._timer.start(int(period_ms))

    def stop(self):
        """Stop the periodic timer."""
        if self._timer.isActive():
            self._timer.stop()
        try:
            if self._callback:
                self._timer.timeout.disconnect(self._callback)
        except Exception:
            pass
        self._callback = None
