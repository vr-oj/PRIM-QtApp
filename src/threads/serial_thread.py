import csv, math, time, serial
from PyQt5.QtCore import QThread, pyqtSignal

class SerialThread(QThread):
    data_ready = pyqtSignal(int, float, float)

    def __init__(self, port=None, baud=115200, test_csv=None):
        super().__init__()
        self.running = True; self.test_csv = test_csv; self.fake_t = 0
        if port:
            self.ser = serial.Serial(port, baud, timeout=1)
        else:
            self.ser, self.start_time = None, time.time()
            if test_csv:
                self.csvfile = open(test_csv); self.reader = csv.reader(self.csvfile)

    def run(self):
        while self.running:
            if self.ser:
                line = self.ser.readline().decode().strip()
                if not line: continue
                parts = line.split(',')
                try:
                    f = int(parts[0]); t = float(parts[1]); p = float(parts[2])
                except:
                    continue
                self.data_ready.emit(f, t, p)
            else:
                t = time.time()-self.start_time
                p = 50+10*math.sin(t*2*math.pi*0.5)
                f = self.fake_t; self.fake_t+=1
                self.data_ready.emit(f, t, p)
                self.msleep(100)

    def stop(self):
        self.running = False
        if hasattr(self,'ser') and self.ser: self.ser.close()
        if hasattr(self,'csvfile') and self.test_csv: self.csvfile.close()
