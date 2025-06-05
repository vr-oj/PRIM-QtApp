import os
import csv
import queue
import tifffile
from PyQt5.QtCore import QThread, pyqtSlot


class RecordingThread(QThread):
    """
    QThread that pairs each incoming serial packet (frame_idx, elapsed_time, pressure)
    with exactly one camera-triggered frame (emitted via camera_thread.frame_for_save).
    Workflow:
      1) Upon SerialThread.data_ready → enqueue_serial_data(idx, time, pressure)
      2) Upon SDKCameraThread.frame_for_save(arr) → enqueue_triggered_frame(arr)
      3) In run(): for every serial packet, block until next triggered frame arrives, then write both to disk:
           - CSV line: [idx, elapsed_time, pressure]
           - TIFF page: the corresponding NumPy array
      4) Exit cleanly when stop() is called.
    """

    def __init__(self, serial_thread, camera_thread, record_dir, parent=None):
        super().__init__(parent)
        self.serial_thread = serial_thread
        self.camera_thread = camera_thread
        self.record_dir = record_dir

        # Queues for pending serial packets and triggered frames
        self.data_queue = queue.Queue()
        self.frame_queue = queue.Queue()
        self._running = True

        # Connect signals
        self.serial_thread.data_ready.connect(self.enqueue_serial_data)
        self.camera_thread.frame_for_save.connect(self.enqueue_triggered_frame)

    @pyqtSlot(int, float, float)
    def enqueue_serial_data(self, frame_idx, elapsed_time, pressure_value):
        """
        Slot for SerialThread data_ready(int, float, float).
        Enqueue the triple if still running.
        """
        if self._running:
            self.data_queue.put((frame_idx, elapsed_time, pressure_value))

    @pyqtSlot(object)
    def enqueue_triggered_frame(self, arr):
        """
        Slot for SDKCameraThread.frame_for_save(np.ndarray).
        Enqueue the raw frame array if still running.
        """
        if self._running:
            # Store the NumPy array directly
            self.frame_queue.put(arr.copy())

    def run(self):
        # 1) Prepare CSV file
        csv_path = os.path.join(self.record_dir, "experiment_data.csv")
        print(f"[RecordingThread] Opening CSV → {csv_path}")
        try:
            csv_file = open(csv_path, "w", newline="")
        except Exception as e:
            print(f"[RecordingThread] ERROR opening CSV: {e}")
            return
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(["frame_index", "elapsed_time_s", "pressure_value"])

        # 2) Prepare multipage TIFF writer
        tiff_path = os.path.join(self.record_dir, "experiment_video.tiff")
        print(f"[RecordingThread] Opening TIFF → {tiff_path}")
        try:
            tiff_writer = tifffile.TiffWriter(tiff_path, bigtiff=False, append=False)
        except Exception as e:
            print(f"[RecordingThread] ERROR opening TIFF: {e}")
            csv_file.close()
            return

        # 3) Main loop: pair each serial packet with a triggered frame
        while self._running:
            try:
                pkt_idx, pkt_time, pkt_pressure = self.data_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            # Write CSV row
            csv_writer.writerow([pkt_idx, f"{pkt_time:.6f}", f"{pkt_pressure:.6f}"])
            csv_file.flush()

            # Now block until the matching triggered frame arrives
            try:
                arr = self.frame_queue.get(timeout=1.0)
            except queue.Empty:
                print(
                    f"[RecordingThread] WARN: no triggered frame for serial idx={pkt_idx}"
                )
                continue

            # Write the NumPy array as one page in the TIFF
            try:
                print(
                    f"[RecordingThread] Writing TIFF page for serial idx={pkt_idx}, shape={arr.shape}"
                )
                tiff_writer.write(arr, photometric="minisblack")
            except Exception as e:
                print(f"[RecordingThread] ERROR writing TIFF page @ idx={pkt_idx}: {e}")

        # 4) Clean up
        print("[RecordingThread] Stopping; closing CSV+TIFF …")
        try:
            tiff_writer.close()
        except Exception as e:
            print(f"[RecordingThread] ERROR closing TIFF: {e}")
        try:
            csv_file.close()
        except Exception as e:
            print(f"[RecordingThread] ERROR closing CSV: {e}")

    def stop(self):
        """
        Stop recording: terminate run(), close files, and disconnect signals.
        """
        self._running = False
        self.wait()
        try:
            self.serial_thread.data_ready.disconnect(self.enqueue_serial_data)
            self.camera_thread.frame_for_save.disconnect(self.enqueue_triggered_frame)
        except Exception:
            pass
