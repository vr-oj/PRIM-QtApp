import os, csv, threading
from queue import Queue, Empty
from tifffile import TiffWriter
from PyQt5.QtCore import QThread, pyqtSignal


class RecordingThread(QThread):
    error = pyqtSignal(str)

    def __init__(self, out_dir, tiff_name, csv_name, fps=None, parent=None):
        super().__init__(parent)
        self.frames_q = Queue(maxsize=100)
        self.data_q = Queue(maxsize=100)
        self.out_dir = out_dir
        self.tiff_name = tiff_name
        self.csv_name = csv_name
        self.fps = fps
        self._stop_flag = threading.Event()
        self.frames_written = 0

    def run(self):
        # open TIFF writer and CSV writer
        tiff_path = os.path.join(self.out_dir, self.tiff_name)
        csv_path = os.path.join(self.out_dir, self.csv_name)
        try:
            with TiffWriter(tiff_path, bigtiff=True) as tif, open(
                csv_path, "w", newline=""
            ) as cf:
                writer = csv.writer(cf)
                writer.writerow(["timestamp", "frame_index", "pressure"])
                while not self._stop_flag.is_set():
                    try:
                        frame_idx, frame = self.frames_q.get(timeout=0.1)
                        self.frames_written += 1
                    except Empty:
                        pass
                    try:
                        row = self.data_q.get(timeout=0.1)
                        writer.writerow(row)
                    except Empty:
                        pass
        except Exception as e:
            self.error.emit(str(e))

    def enqueue_frame(self, frame_index, frame):
        try:
            self.frames_q.put_nowait((frame_index, frame))
        except:
            pass  # drop if full

    def enqueue_data(self, timestamp, frame_index, pressure):
        try:
            self.data_q.put_nowait((timestamp, frame_index, pressure))
        except:
            pass

    def stop(self):
        self._stop_flag.set()
        self.wait()
