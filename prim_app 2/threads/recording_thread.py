# prim_app/threads/recording_thread.py

import os
import csv
import queue
import numpy as np
import tifffile
from PyQt5.QtCore import QThread, pyqtSlot


class RecordingThread(QThread):
    """
    QThread that:
      1) Listens for “(frame_idx, elapsed_time, pressure)” from SerialThread.data_ready
      2) Whenever a packet arrives: write the CSV line, then grab exactly one frame from IC4
         (using the passed-in grabber), flame it into a multi‐page TIFF.
      3) Exit cleanly when told to stop.
    """

    def __init__(self, serial_thread, grabber, record_dir, parent=None):
        super().__init__(parent)

        # Instead of holding a pyserial object, we hold the SerialThread instance
        self.serial_thread = serial_thread

        # The IC4 grabber (already started/opened) that we will call `.CaptureSA()` on:
        self.grabber = grabber

        # Where to write CSV + multipage-TIFF
        self.record_dir = record_dir

        # A thread‐safe queue to store incoming data packets
        self.data_queue = queue.Queue()

        # Keep running until stop() is called
        self._running = True

        # Connect SerialThread.data_ready → self.enqueue_data
        # SerialThread emits (idx:int, t:float, p:float)
        self.serial_thread.data_ready.connect(self.enqueue_data)

    @pyqtSlot(int, float, float)
    def enqueue_data(self, frame_idx, elapsed_time, pressure_value):
        """
        This slot is invoked every time SerialThread emits .data_ready(idx, t, p).
        We simply put the triple into our queue so that run() can process it.
        """
        # Do not enqueue if user has already stopped recording
        if self._running:
            self.data_queue.put((frame_idx, elapsed_time, pressure_value))

    def run(self):
        # ─── 1) Prepare CSV on disk ─────────────────────────────────────────────────
        csv_path = os.path.join(self.record_dir, "experiment_data.csv")
        try:
            csv_file = open(csv_path, "w", newline="")
        except Exception as e:
            print(f"[RecordingThread] ERROR opening CSV: {e}")
            return

        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(["frame_index", "elapsed_time_s", "pressure_value"])

        # ─── 2) Prepare TIFF Writer ─────────────────────────────────────────────────
        tiff_path = os.path.join(self.record_dir, "experiment_video.tiff")
        try:
            # bigtiff=False is fine unless your run is >4GB
            tiff_writer = tifffile.TiffWriter(tiff_path, bigtiff=False)
        except Exception as e:
            print(f"[RecordingThread] ERROR opening TIFF: {e}")
            try:
                csv_file.close()
            except:
                pass
            return

        # ─── 3) Main loop: pop (idx, t, p) from queue, write CSV, then capture one frame ───
        while self._running:
            try:
                idx, t, p = self.data_queue.get(timeout=0.1)
            except queue.Empty:
                continue  # no new packet—loop again

            # 3a) Write CSV row
            csv_writer.writerow([idx, f"{t:.6f}", f"{p:.6f}"])
            csv_file.flush()

            # 3b) Immediately grab one frame from the IC4 grabber
            try:
                # CaptureSA returns a NumPy array (height x width x channels)
                shot = self.grabber.CaptureSA()
                # Convert to 8‐bit if needed
                # (assume CAPTURESA already returns 8‐bit [0..255], or else you can scale)
                if shot is not None:
                    # Write one page/frame to the multipage-TIFF
                    tiff_writer.write(shot, photometric="minisblack")
            except Exception as e:
                print(f"[RecordingThread] WARNING: failed to grab TIFF frame: {e}")
                # We continue even if a frame is missing; CSV is already written.

        # ─── 4) Clean up on exit ──────────────────────────────────────────────────────
        try:
            tiff_writer.close()
        except Exception:
            pass

        try:
            csv_file.close()
        except Exception:
            pass

    def stop(self):
        """
        Called from the main/UI thread to gracefully stop recording.
        """
        self._running = False
        self.wait()  # block until run() finishes
        # Disconnect the SerialThread signal so we don't enqueue after stop()
        try:
            self.serial_thread.data_ready.disconnect(self.enqueue_data)
        except Exception:
            pass
