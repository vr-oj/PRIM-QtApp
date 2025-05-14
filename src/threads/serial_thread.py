import csv, math, time, serial
from PyQt5.QtCore import QThread, pyqtSignal

class SerialThread(QThread):
    # emits (frameCount, time_s, pressure)
    data_ready = pyqtSignal(int, float, float)

    def __init__(self, port=None, baud=115200, test_csv=None):
        super().__init__()
        self.running    = True
        self.fake_t     = 0
        self.test_csv   = test_csv

        if port:
            try:
                self.ser = serial.Serial(port, baud, timeout=1)
                print(f"[SerialThread] Opened {port} @ {baud} baud")
            except Exception as e:
                print(f"[SerialThread] ❌ Failed to open {port}: {e}")
                self.ser = None
        else:
            self.ser        = None
            self.start_time = time.time()

    def run(self):
        while self.running:
            if self.ser:
                raw = self.ser.readline()
                if not raw:
                    continue
                line = raw.decode('utf-8', errors='ignore').strip()
                print(f"[SerialThread] RAW: {line}")  # debug

                parts = line.split(',')
                if len(parts) < 3:
                    continue
                try:
                    frame = int(parts[0])
                    t     = float(parts[1])
                    p     = float(parts[2])
                except ValueError:
                    continue

                # Emit to plot
                self.data_ready.emit(frame, t, p)

            else:
                # simulated sine‐wave data at ~10 Hz
                t = time.time() - self.start_time
                p = 50 + 10 * math.sin(t * 2 * math.pi * 0.5)
                f = self.fake_t
                self.fake_t += 1
                print(f"[SerialThread] SIM: frame={f}, t={t:.3f}, p={p:.1f}")  # debug
                self.data_ready.emit(f, t, p)
                self.msleep(100)

    def stop(self):
        self.running = False
        if hasattr(self, 'ser') and self.ser:
            self.ser.close()
