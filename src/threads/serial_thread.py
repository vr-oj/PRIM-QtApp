import math, time

class SerialThread(QThread):
    data_ready = pyqtSignal(float, float)

    def __init__(self, port=None, baud=115200, test_csv=None):
        super().__init__()
        self.running = True
        if port:
            self.ser = serial.Serial(port, baud, timeout=1)
            self.test_csv = None
        else:
            self.ser = None
            self.test_csv = test_csv
            if test_csv:
                import csv
                self.csvfile = open(test_csv)
                self.reader = csv.reader(self.csvfile)
            self.start_time = time.time()

        self.fake_t = 0

    def run(self):
        while self.running:
            if self.ser:
                line = self.ser.readline().decode().strip()
                # parse as before…
            else:
                # generate a fake sine-wave pressure
                t = time.time() - self.start_time
                p = 50 + 10 * math.sin(t * 2 * math.pi * 0.5)  # 0.5 Hz
                self.data_ready.emit(t, p)
                self.msleep(100)  # 10 Hz

    def stop(self):
        self.running = False
        if self.ser:
            self.ser.close()
        elif self.test_csv:
            self.csvfile.close()