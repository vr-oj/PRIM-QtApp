from abc import ABC, abstractmethod
import logging
from PyQt5.QtCore import QObject, pyqtSignal, QThread
import serial
import time

log = logging.getLogger(__name__)


class IArduinoController(QObject, ABC):
    """Abstract interface for communicating with the Arduino controller."""

    data_packet = pyqtSignal(int, float, float)
    """Emitted when a line of data is received: (master_ts_ns, arduino_ts_s, pressure)."""

    @abstractmethod
    def send_command(self, cmd: str):
        """Send an ASCII command string to the Arduino."""
        raise NotImplementedError


class ArduinoSerialController(IArduinoController):
    """Simple serial implementation of :class:`IArduinoController`."""

    def __init__(self, port: str, baud: int = 115200, parent=None):
        super().__init__(parent)
        self.port = port
        self.baud = baud
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run)
        self._stop = False
        self._serial = None

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop = True
        self._thread.quit()
        self._thread.wait()
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None

    def send_command(self, cmd: str):
        if self._serial and self._serial.is_open:
            try:
                self._serial.write(cmd.encode('utf-8'))
            except Exception as e:
                log.error(f"Serial write failed: {e}")

    def _run(self):
        try:
            self._serial = serial.Serial(self.port, self.baud, timeout=1)
        except Exception as e:
            log.error(f"Failed to open serial port {self.port}: {e}")
            return

        while not self._stop:
            try:
                line = self._serial.readline()
            except Exception:
                break
            if not line:
                continue
            try:
                text = line.decode('utf-8').strip()
                parts = [p.strip() for p in text.split(',')]
                if len(parts) >= 3:
                    idx = int(parts[0])
                    t = float(parts[1])
                    p = float(parts[2])
                    from utils.sync_manager import SyncManager
                    ts = SyncManager.now()
                    self.data_packet.emit(ts, t, p)
            except Exception as e:
                log.warning(f"Malformed serial line '{line}': {e}")

        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
