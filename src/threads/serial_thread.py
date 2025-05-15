import csv, math, time, serial, os, logging
from PyQt5.QtCore import QThread, pyqtSignal

class SerialThread(QThread):
    # emits (frameCount, time_s, pressure)
    data_ready = pyqtSignal(int, float, float)

    def __init__(self, port=None, baud=115200, test_csv=None):
        super().__init__()
        self.fake_t   = 0
        self.test_csv = test_csv

        # Always define start_time for simulation
        self.start_time = time.time()

        if port:
            try:
                self.ser = serial.Serial(port, baud, timeout=1)
                log.info(f"Opened serial port {port} @ {baud} baud")
            except Exception as e:
                log.warning(f"Failed to open serial port {port}: {e}")
                self.ser = None
        else:
            self.ser = None

    def run(self):
        # ensure the thread flag is set
        self.running = True
        try:
            # main loop
            while self.running:
                if self.ser:
                    raw = self.ser.readline()
                    if not raw:
                        continue
                    line = raw.decode('utf-8', errors='ignore').strip()

                    parts = [fld.strip() for fld in line.split(',')]
                    if len(parts) < 3:
                        continue

                    try:
                        t     = float(parts[0])
                        frame = int(parts[1])
                        p     = float(parts[2])
                    except Exception as e:
                        log.error(f"Parse error: {e}")
                        continue

                    self.data_ready.emit(frame, t, p)
                else:
                    # simulated sine‑wave data at ~10 Hz
                    t = time.time() - self.start_time
                    p = 50 + 10 * math.sin(t * math.pi)
                    f = self.fake_t
                    self.fake_t += 1
                    self.data_ready.emit(f, t, p)
                    self.msleep(100)
        except Exception as e:
            log.exception(f"Unexpected error in run(): {e}")
        finally:
            self.running = False
            if getattr(self, 'ser', None):
                try:
                    self.ser.close()
                except Exception:
                    log.exception("Error closing serial port in run()")


    def stop(self):
        self.running = False
        # join thread automatically when QThread stops
