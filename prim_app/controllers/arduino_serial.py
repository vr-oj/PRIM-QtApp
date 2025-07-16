import serial
from .interfaces import IArduinoController


class ArduinoSerialController(IArduinoController):
    """Minimal serial-based controller for the PRIM Arduino."""

    def __init__(self, port: str, baud: int = 115200):
        self.port = port
        self.baud = baud
        self.ser = None

    def open(self):
        self.ser = serial.Serial(self.port, self.baud, timeout=1)

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.ser = None

    def send_sync(self) -> int:
        if not self.ser:
            return -1
        self.ser.write(b"SYNC\n")
        line = self.ser.readline().decode().strip()
        if line.startswith("SYNC,"):
            try:
                return int(line.split(",", 1)[1])
            except (IndexError, ValueError):
                return -1
        return -1

    def send_trigger(self):
        if self.ser:
            self.ser.write(b"TRIG\n")

    def read_packet(self):
        if not self.ser:
            return None
        line = self.ser.readline().decode().strip()
        if not line:
            return None
        try:
            frame, ts, pressure = line.split(",")
            return int(frame), float(ts), float(pressure)
        except ValueError:
            return None
