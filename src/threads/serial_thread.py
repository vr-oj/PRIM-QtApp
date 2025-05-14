import csv, math, time, serial, os, logging
from PyQt5.QtCore import QThread, pyqtSignal

# top‐level load confirmation
logging.basicConfig(level=logging.DEBUG,
                    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")
log = logging.getLogger(__name__)
log.debug(f"LOADING SerialThread from {os.path.abspath(__file__)}")

class SerialThread(QThread):
    # emits (frameCount, time_s, pressure)
    data_ready = pyqtSignal(int, float, float)

    def __init__(self, port=None, baud=115200, test_csv=None):
        super().__init__()
        self.fake_t   = 0
        self.test_csv = test_csv

        log.debug(f"__init__ called, port = {port}, baud = {baud}")

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
        # now we enter the loop
        self.running = True
        try:
            while self.running:
            if self.ser:
                raw = self.ser.readline()
                if not raw:
                    continue
                line = raw.decode('utf-8', errors='ignore').strip()
                log.debug(f"RAW: {line}")

                # split and strip whitespace
                parts = [fld.strip() for fld in line.split(',')]
                if len(parts) < 3:
                    continue

                try:
                    # parts[0] = time, parts[1] = frame, parts[2] = pressure
                    t     = float(parts[0])
                    frame = int(parts[1])
                    p     = float(parts[2])
                except Exception as e:
                    log.error(f"Parse error: {e}")
                    continue

                # emit in the order your slot expects (frame, t, p)
                self.data_ready.emit(frame, t, p)
                log.debug(f"EMIT → frame={frame}, t={t:.3f}, p={p:.1f}")

            else:
                # simulated sine‑wave data at ~10 Hz
                t = time.time() - self.start_time
                p = 50 + 10 * math.sin(t * math.pi)  # 0.5 Hz sine
                f = self.fake_t
                self.fake_t += 1
                log.debug(f"SIM: frame={f}, t={t:.3f}, p={p:.1f}")
                self.data_ready.emit(f, t, p)
                self.msleep(100)
        except Exception as e:
            log.exception(f"Unexpected error in run(): {e}")
        finally:
            self.running = False
            if getattr(self, 'ser', None):
                try:
                    self.ser.close()
                    log.debug("Serial port closed in run()")
                except Exception:
                    log.exception("Error closing serial port")

    def stop(self):
        log.debug("stop() called")
        self.running = False
        # join thread automatically when QThread stops
