# serial_thread.py

import csv
import math
import time
import serial
from PyQt5.QtCore import QThread, pyqtSignal

class SerialThread(QThread):
    # now emits frameCount, time_s, pressure
    data_ready = pyqtSignal(int, float, float)

    def __init__(self, port=None, baud=115200, test_csv=None):
        super().__init__()
        self.running = True
        self.test_csv = test_csv

        if port:
            self.ser = serial.Serial(port, baud, timeout=1)
        else:
            self.ser = None
            if test_csv:
                self.csvfile = open(test_csv)
                self.reader = csv.reader(self.csvfile)
            self.start_time = time.time()

        self.fake_t = 0

    def run(self):
        while self.running:
            if self.ser:
                line = self.ser.readline().decode('utf-8').strip()
                if not line:
                    continue

                parts = line.split(',')
                try:
                    frame = int(parts[0])
                    t     = float(parts[1])
                    p     = float(parts[2])
                except (IndexError, ValueError):
                    continue

                self.data_ready.emit(frame, t, p)

            else:
                # Fake sine-wave data when no serial port
                t = time.time() - self.start_time
                p = 50 + 10 * math.sin(t * 2 * math.pi * 0.5)
                frame = self.fake_t
                self.fake_t += 1
                self.data_ready.emit(frame, t, p)
                self.msleep(100)  # emit at ~10 Hz

    def stop(self):
        self.running = False
        if self.ser:
            self.ser.close()
        elif self.test_csv:
            self.csvfile.close()
