# File: prim_app/recording.py

import os
import time
import csv
import json
import queue
import logging
import tifffile
from PyQt5.QtCore import QThread

log = logging.getLogger(__name__)


class SimpleVideoRecorder:
    """
    Writes a multi‐page TIFF stack. Each page gets a JSON‐encoded ImageDescription tag
    containing: frame_index, camera_timestamp_us, arduino_timestamp_us, pressure_mmHg.
    """

    def __init__(
        self, out_path, fps, video_ext="tif", video_codec=None, frame_size=None
    ):
        """
        out_path: base filename (no extension). We'll append ".tif".
        fps, video_codec, frame_size: not used here (TIFF ignores fps/codec), but kept
            for API compatibility if you support AVI fallback later.
        """
        self.video_ext = video_ext.lower()
        if self.video_ext not in ("tif", "tiff"):
            raise ValueError(
                f"SimpleVideoRecorder only supports TIFF in this version, got '{video_ext}'"
            )

        # Build the full path, ensure directories exist
        self.out_path = f"{out_path}.{self.video_ext}"
        dirname = os.path.dirname(self.out_path)
        if dirname and not os.path.isdir(dirname):
            os.makedirs(dirname, exist_ok=True)

        self.frames_written = 0
        log.info(f"SimpleVideoRecorder initialized: {self.out_path}")

    def write_frame_with_metadata(
        self,
        frame_numpy,
        frame_idx: int,
        cam_ts: int,
        arduino_ts_us: int,
        pressure: float,
    ):
        """
        Write a single frame (NumPy array) as the next page in the TIFF.
        frame_numpy: 2D or 3D NumPy array (uint8 or uint16). Typically mono‐channel.
        frame_idx: integer camera‐side frame index.
        cam_ts: camera‐side timestamp (integer, in µs).
        arduino_ts_us: Arduino‐side timestamp (integer, in µs) from serial.
        pressure: float (mmHg).
        """
        # Build JSON metadata
        meta = {
            "frame_index": int(frame_idx),
            "camera_timestamp_us": int(cam_ts),
            "arduino_timestamp_us": int(arduino_ts_us),
            "pressure_mmHg": float(pressure),
        }
        description = json.dumps(meta)

        try:
            # On first frame, create file; on subsequent, append
            tifffile.imwrite(
                self.out_path,
                frame_numpy,
                append=(self.frames_written > 0),
                description=description,
            )
            self.frames_written += 1
        except Exception as e:
            log.error(
                f"Error writing TIFF frame (idx={frame_idx}) to '{self.out_path}': {e}"
            )
            raise

    def stop(self):
        """
        Nothing special to close for TIFF stacks (tifffile finalizes on write),
        but we can log and reset if needed.
        """
        log.info(
            f"SimpleVideoRecorder: stopped. Total frames written: {self.frames_written}"
        )


class CSVRecorder:
    """
    Writes a CSV file with columns: time_s, frame_index, pressure_mmHg.
    """

    def __init__(self, filename):
        """
        filename: full path to CSV (including ".csv").
        """
        dirname = os.path.dirname(filename)
        if dirname and not os.path.isdir(dirname):
            os.makedirs(dirname, exist_ok=True)

        self.filename = filename
        try:
            self.file = open(self.filename, "w", newline="")
            self.writer = csv.writer(self.file)
            # Write header
            self.writer.writerow(["time_s", "frame_index", "pressure_mmHg"])
            self.is_recording = True
            log.info(f"CSVRecorder initialized: {self.filename}")
        except Exception as e:
            log.error(f"Failed to open CSV '{self.filename}' for writing: {e}")
            raise

    def write_data(self, t_s, frame_idx, pressure):
        """
        t_s: float (seconds). frame_idx: int. pressure: float (mmHg).
        """
        if self.is_recording:
            try:
                self.writer.writerow([f"{t_s:.6f}", frame_idx, f"{pressure:.6f}"])
            except Exception as e:
                log.error(
                    f"Error writing CSV row ({t_s}, {frame_idx}, {pressure}): {e}"
                )
        else:
            raise RuntimeError("CSVRecorder is not active; cannot write data.")

    def stop(self):
        """
        Close the CSV file cleanly.
        """
        if not self.is_recording:
            return
        try:
            self.file.close()
            log.info(f"CSVRecorder: stopped and closed '{self.filename}'.")
        except Exception as e:
            log.error(f"Error closing CSV '{self.filename}': {e}")
        finally:
            self.is_recording = False


class TrialRecorder:
    """
    Combines a SimpleVideoRecorder (TIFF) and CSVRecorder into a single interface.
    Automatically appends timestamps.
    """

    def __init__(self, basepath, fps, frame_size, video_ext="tif", video_codec=None):
        """
        basepath: base filename without extension, to which a timestamp will be appended.
        fps, frame_size, video_ext, video_codec: passed to SimpleVideoRecorder.
        """
        # Use a timestamp suffix to avoid overwriting existing files
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.base_filename = f"{basepath}_{ts}"
        self.is_recording_active = False

        try:
            # Initialize TIFF writer
            self.video_recorder = SimpleVideoRecorder(
                out_path=self.base_filename,
                fps=fps,
                video_ext=video_ext,
                video_codec=video_codec,
                frame_size=frame_size,
            )
            # Initialize CSV writer
            csv_path = f"{self.base_filename}.csv"
            self.csv_recorder = CSVRecorder(csv_path)

            self.is_recording_active = True
            log.info(f"TrialRecorder ready: base='{self.base_filename}'")
        except Exception as e:
            log.error(f"TrialRecorder initialization failed: {e}")
            # Clean up any partial writer
            if hasattr(self, "video_recorder") and self.video_recorder:
                try:
                    self.video_recorder.stop()
                except:
                    pass
            if hasattr(self, "csv_recorder") and self.csv_recorder:
                try:
                    self.csv_recorder.stop()
                except:
                    pass
            raise

    def write_video_frame_with_metadata(
        self, frame_numpy, frame_idx, cam_ts, arduino_ts_us, pressure
    ):
        """
        Write one TIFF page with embedded metadata.
        """
        if not self.is_recording_active:
            raise RuntimeError("TrialRecorder is not active; cannot write video.")
        self.video_recorder.write_frame_with_metadata(
            frame_numpy, frame_idx, cam_ts, arduino_ts_us, pressure
        )

    def write_csv_data(self, t_s, frame_idx, pressure):
        """
        Write one CSV row.
        """
        if not self.is_recording_active:
            raise RuntimeError("TrialRecorder is not active; cannot write CSV.")
        self.csv_recorder.write_data(t_s, frame_idx, pressure)

    def stop(self):
        """
        Stop both TIFF and CSV writers.
        """
        if not self.is_recording_active:
            return
        try:
            if self.video_recorder:
                self.video_recorder.stop()
        except Exception as e:
            log.error(f"Error stopping SimpleVideoRecorder: {e}")
        try:
            if self.csv_recorder:
                self.csv_recorder.stop()
        except Exception as e:
            log.error(f"Error stopping CSVRecorder: {e}")
        self.is_recording_active = False
        log.info("TrialRecorder: stopped.")


class RecordingWorker(QThread):
    """
    A background thread that consumes pairs of (“video”, (frame_arr, frame_idx, cam_ts, arduino_ts, pressure))
    and (“csv”, (arduino_ts_us, pressure)) from a thread‐safe queue, pairs them FIFO‐style, and writes them out.

    - Call add_video_frame((arr, frame_idx, cam_ts, a_ts, pressure)) whenever a new frame arrives.
      Note: a_ts, pressure may be None at that call; the worker will pair with the next CSV entry it sees.
    - Call add_csv_data(arduino_ts_us, pressure) whenever the Arduino emits a new line.
    - Call stop_worker() to signal end‐of‐recording; worker will drain remaining items, then exit run().
    """

    def __init__(
        self, basepath, fps, frame_size, video_ext="tif", video_codec=None, parent=None
    ):
        super().__init__(parent)
        self.basepath = basepath
        self.fps = fps
        self.frame_size = frame_size
        self.video_ext = video_ext
        self.video_codec = video_codec

        self.trial_recorder = None
        self.data_queue = queue.Queue()
        self._is_running = False
        self._pending_csv = []  # list of (arduino_ts_us, pressure)
        self._pending_video = (
            []
        )  # list of (frame_arr, frame_idx, cam_ts, arduino_ts_us, pressure)

    def run(self):
        # ➊ Initialize the TrialRecorder
        try:
            self.trial_recorder = TrialRecorder(
                basepath=self.basepath,
                fps=self.fps,
                frame_size=self.frame_size,
                video_ext=self.video_ext,
                video_codec=self.video_codec,
            )
            if not self.trial_recorder.is_recording_active:
                log.error("RecordingWorker: TrialRecorder failed to activate.")
                return
            self._is_running = True
            log.info("RecordingWorker: started and ready to record.")
        except Exception as e:
            log.exception(f"RecordingWorker: could not initialize TrialRecorder: {e}")
            return

        # ➋ Main loop: consume items from data_queue until stop + queue empty
        try:
            while True:
                # If stop requested and queue is drained, break
                if not self._is_running and self.data_queue.empty():
                    break

                try:
                    item_type, data = self.data_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                if item_type == "stop":
                    # Received signal to stop; process any leftover then exit
                    self._is_running = False
                    self.data_queue.task_done()
                    continue

                if item_type == "video":
                    # data = (frame_arr, frame_idx, cam_ts, arduino_ts_us (or None), pressure (or None))
                    self._pending_video.append(data)

                elif item_type == "csv":
                    # data = (arduino_ts_us, pressure)
                    self._pending_csv.append(data)

                else:
                    log.warning(f"RecordingWorker: unknown item_type '{item_type}'")
                    self.data_queue.task_done()
                    continue

                # Attempt to flush as many paired items as possible
                while self._pending_video and self._pending_csv:
                    # Pop the oldest video and oldest CSV
                    frame_arr, frame_idx, cam_ts, a_ts_placeholder, pres_placeholder = (
                        self._pending_video.pop(0)
                    )
                    arduino_ts_us, pressure = self._pending_csv.pop(0)

                    # If the video tuple didn’t already contain arduino_ts_us/pressure, fill them
                    arduino_ts_for_frame = arduino_ts_us
                    pressure_for_frame = pressure

                    # 1) Write TIFF page with metadata
                    try:
                        self.trial_recorder.write_video_frame_with_metadata(
                            frame_arr,
                            frame_idx,
                            cam_ts,
                            arduino_ts_for_frame,
                            pressure_for_frame,
                        )
                    except Exception as e:
                        log.error(
                            f"RecordingWorker: error writing video frame {frame_idx}: {e}"
                        )

                    # 2) Write CSV row (arduino_ts_us converted to seconds)
                    try:
                        t_s = arduino_ts_for_frame / 1e6
                        self.trial_recorder.write_csv_data(
                            t_s, frame_idx, pressure_for_frame
                        )
                    except Exception as e:
                        log.error(
                            f"RecordingWorker: error writing CSV for frame {frame_idx}: {e}"
                        )

                self.data_queue.task_done()

        except Exception as e:
            log.exception(f"RecordingWorker: unexpected error in run(): {e}")

        finally:
            log.info("RecordingWorker: stopping TrialRecorder.")
            if self.trial_recorder:
                try:
                    self.trial_recorder.stop()
                except Exception as e:
                    log.error(f"RecordingWorker: error stopping TrialRecorder: {e}")
            self._is_running = False
            log.info("RecordingWorker: finished.")

    def add_video_frame(self, payload):
        """
        Called from the camera thread (via MainWindow), payload is a tuple:
          (frame_numpy, frame_idx, cam_ts, arduino_ts_us (or None), pressure (or None))
        Typically MainWindow will call add_video_frame((arr, frame_idx, cam_ts, None, None))
        and rely on RecordingWorker to match it to the next CSV entry.
        """
        if self._is_running:
            self.data_queue.put(("video", payload))
        else:
            log.warning(
                "RecordingWorker.add_video_frame() called but worker is not running."
            )

    def add_csv_data(self, arduino_time_us, pressure):
        """
        Called from the SerialThread (via MainWindow). Puts (arduino_time_us, pressure)
        into the queue so it can be paired with the next video frame.
        """
        if self._is_running:
            self.data_queue.put(("csv", (arduino_time_us, pressure)))
        else:
            log.warning(
                "RecordingWorker.add_csv_data() called but worker is not running."
            )

    def stop_worker(self):
        """
        Signal the worker to finish processing and exit.  Subsequent items in the queue
        will still be paired and written out before actual thread exit.
        """
        if self._is_running:
            self.data_queue.put(("stop", None))
        else:
            log.warning(
                "RecordingWorker.stop_worker() called but worker already not running."
            )

    @property
    def is_ready_to_record(self):
        """
        True if the TrialRecorder has been initialized and is active.
        """
        return (self.trial_recorder is not None) and (
            self.trial_recorder.is_recording_active
        )
