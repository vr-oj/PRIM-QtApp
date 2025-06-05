# prim_app/threads/recording_thread.py
import os
import csv
import numpy as np
import tifffile
from PyQt5.QtCore import QThread


class RecordingThread(QThread):
    """
    QThread that continuously:
      1. Reads one line from the Arduino’s serial port (expects 'frame_idx,elapsed_s,pressure')
      2. Pulls exactly one frame from IC4’s StreamSink (camera)
      3. Writes that CSV row and TIFF page with embedded metadata
    """

    def __init__(self, serial_port, grabber, record_dir, parent=None):
        super().__init__(parent)
        self.serial_port = (
            serial_port  # a pyserial Serial instance, already open @ 115200
        )
        self.grabber = grabber  # an IC4 Grabber that has been opened
        self.record_dir = record_dir  # directory path where CSV+TIFF will be saved
        self._running = True

    def run(self):
        # ─── Prepare CSV ─────────────────────────────────────────────────────────
        csv_path = os.path.join(self.record_dir, "experiment_data.csv")
        try:
            csv_file = open(csv_path, "w", newline="")
        except Exception as e:
            print(f"[RecordingThread] ERROR opening CSV: {e}")
            return

        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(["frame_index", "elapsed_time_s", "pressure_value"])

        # ─── Prepare TIFF Writer ────────────────────────────────────────────────
        tiff_path = os.path.join(self.record_dir, "experiment_video.tiff")
        try:
            # bigtiff=False is fine unless your run is extremely large (>4 GB)
            tiff_writer = tifffile.TiffWriter(tiff_path, bigtiff=False)
        except Exception as e:
            print(f"[RecordingThread] ERROR opening TIFF: {e}")
            csv_file.close()
            return

        # ─── Main Loop: Read Serial + Pull Image + Write CSV+TIFF ───────────────
        while self._running:
            # 1) Read one line from Arduino
            try:
                raw_line = self.serial_port.readline()
                if not raw_line:
                    continue  # timeout or nothing received
                line = raw_line.decode("utf-8", errors="ignore").strip()
                parts = [p.strip() for p in line.split(",")]
                if len(parts) != 3:
                    continue  # skip any malformed line
                frame_idx = int(parts[0])
                elapsed_s = float(parts[1])
                pressure = float(parts[2])
            except Exception:
                # If parsing fails, skip and try again
                continue

            # 2) Pull exactly one frame from the camera’s StreamSink
            try:
                # NOTE: adjust timeout_ms if you expect longer delays
                img = self.grabber.stream_sink.pull_image(timeout_ms=1000)
                # Convert to NumPy. Depending on your IC4 version, you might call `img.to_numpy()`
                # or `np.frombuffer(img.buffer, dtype=...)` etc. Here we assume to_numpy() returns a 2D array.
                frame_array = img.to_numpy()
            except Exception:
                # If the camera frame is not available in time, skip writing
                continue

            # 3) Write CSV row
            csv_writer.writerow([frame_idx, f"{elapsed_s:.4f}", f"{pressure:.2f}"])
            # (We format floats to reasonable precision, adjust as needed)

            # 4) Append a page to the TIFF with a small metadata tag
            #    Embed a TEXT tag (ImageDescription) that records frame_idx, time, pressure
            description = (
                f"FrameIndex={frame_idx};Time_s={elapsed_s:.4f};Pressure={pressure:.2f}"
            )
            try:
                # If your frame_array is e.g. uint8 or uint16, keep dtype. Otherwise cast:
                if frame_array.dtype != np.uint8 and frame_array.dtype != np.uint16:
                    frame_array = frame_array.astype(np.uint16)

                tiff_writer.write(
                    frame_array,
                    photometric="minisblack",  # grayscale
                    metadata={"Description": description},
                )
            except Exception as e:
                # If writing the TIFF page fails, just continue
                print(f"[RecordingThread] ERROR writing TIFF page: {e}")
                continue

        # ─── Clean Up ─────────────────────────────────────────────────────────────
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
        Call this from the main (UI) thread to terminate recording.
        It will allow the run() loop to exit gracefully, then close files.
        """
        self._running = False
        self.wait()  # blocks until run() actually finishes
