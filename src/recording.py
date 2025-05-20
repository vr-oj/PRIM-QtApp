import os
import time
import csv
import logging
import imageio  # For AVI and potentially other formats
import tifffile  # For TIFF stacks
import queue

log = logging.getLogger(__name__)


class RecordingWorker(QThread):  # New QThread worker
    def __init__(self, basepath, fps, frame_size, video_ext, video_codec, parent=None):
        super().__init__(parent)
        self.basepath = basepath
        self.fps = fps
        self.frame_size = frame_size
        self.video_ext = video_ext
        self.video_codec = video_codec
        self.trial_recorder = None
        self.data_queue = queue.Queue()
        self._is_running = False
        self.video_frame_count_internal = 0

    def run(self):
        self._is_running = True
        try:
            self.trial_recorder = TrialRecorder(
                basepath=self.basepath,
                fps=self.fps,
                frame_size=self.frame_size,
                video_ext=self.video_ext,
                video_codec=self.video_codec,
            )
            if not self.trial_recorder.is_recording:
                # Propagate error if TrialRecorder failed to init
                # (Consider adding an error signal to RecordingWorker)
                log.error("TrialRecorder failed to initialize within RecordingWorker.")
                self._is_running = False
                return

            log.info(f"RecordingWorker started for {self.basepath}")
            while self._is_running or not self.data_queue.empty():
                try:
                    item_type, data = self.data_queue.get(
                        timeout=0.1
                    )  # Timeout to check _is_running
                    if item_type == "stop":
                        break
                    if item_type == "video":
                        self.trial_recorder.write_video_frame(data)
                        self.video_frame_count_internal = (
                            self.trial_recorder.video_frame_count
                        )
                    elif item_type == "csv":
                        t, idx, p = data
                        self.trial_recorder.write_csv_data(t, idx, p)
                    self.data_queue.task_done()
                except queue.Empty:
                    if not self._is_running and self.data_queue.empty():
                        break  # Exit if stopped and queue is empty
                    continue  # Continue waiting if running or queue has pending items
                except Exception as e:
                    log.exception(f"Error processing queue in RecordingWorker: {e}")
                    # Optionally emit an error signal

        except Exception as e:
            log.exception(f"Failed to initialize TrialRecorder in RecordingWorker: {e}")
            # Optionally emit an error signal
        finally:
            if self.trial_recorder:
                self.trial_recorder.stop()
                self.video_frame_count_internal = (
                    self.trial_recorder.video_frame_count
                )  # Update one last time
            log.info("RecordingWorker finished.")
            self._is_running = False

    def add_video_frame(self, frame_numpy):
        if self._is_running:
            self.data_queue.put(("video", frame_numpy))

    def add_csv_data(self, t, idx, p):
        if self._is_running:
            self.data_queue.put(("csv", (t, idx, p)))

    def stop_worker(self):
        log.info("RecordingWorker: Stop requested.")
        if self._is_running:
            self.data_queue.put(("stop", None))  # Sentinel to stop processing
        self._is_running = False

    @property
    def video_frame_count(self):
        if self.trial_recorder:  # Get from TrialRecorder if possible
            return self.trial_recorder.video_frame_count
        return self.video_frame_count_internal  # Fallback to worker's count

    @property
    def is_ready_to_record(self):  # Check if TrialRecorder was successfully initialized
        return (
            self.trial_recorder is not None and self.trial_recorder.is_recording_active
        )


class SimpleVideoRecorder:
    def __init__(
        self, out_path, fps, video_ext="avi", video_codec="MJPG", frame_size=None
    ):  # frame_size is optional for imageio
        self.out_path = f"{out_path}.{video_ext.lower()}"
        self.fps = fps
        self.video_ext = video_ext.lower()
        self.writer = None
        self.frames_written = 0

        # Ensure output directory exists
        dirname = os.path.dirname(self.out_path)
        if dirname:  # If dirname is not empty
            os.makedirs(dirname, exist_ok=True)
        else:  # If out_path is just a filename in the current directory
            os.makedirs(".", exist_ok=True)

        if self.video_ext == "avi":
            self.writer = imageio.get_writer(
                self.out_path, fps=self.fps, codec=video_codec, quality=8
            )
        elif self.video_ext in ("tif", "tiff"):
            # For TIFF, tifffile handles appending. No explicit writer object at init.
            pass
        else:
            log.error(f"Unsupported video extension: {self.video_ext}")
            raise ValueError(f"Unsupported video extension: {self.video_ext}")
        log.info(f"SimpleVideoRecorder initialized for {self.out_path}")

    def write_frame(self, frame_numpy):
        if self.video_ext == "avi" and self.writer:
            self.writer.append_data(frame_numpy)
        elif self.video_ext in ("tif", "tiff"):
            tifffile.imwrite(
                self.out_path, frame_numpy, append=(self.frames_written > 0)
            )
        else:
            # This case should ideally not be reached if constructor raised ValueError
            log.warning(
                f"Attempted to write frame for unsupported/uninitialized recorder: {self.video_ext}"
            )
            return

        self.frames_written += 1

    def stop(self):
        if self.writer and self.video_ext == "avi":
            try:
                self.writer.close()
            except Exception as e:
                log.error(f"Error closing AVI writer: {e}")
        self.writer = None  # Ensure writer is cleared
        log.info(
            f"Stopped SimpleVideoRecorder for {self.out_path} ({self.frames_written} frames)"
        )
        # Do not reset frames_written here if you want to query it after stopping.


class CSVRecorder:  # Keep CSVRecorder as is
    """
    Records timestamped data (time, frame index, pressure) to a CSV file.
    """

    def __init__(self, filename):
        # Ensure output directory exists
        dirname = os.path.dirname(filename)
        if dirname:  # If dirname is not empty
            os.makedirs(dirname, exist_ok=True)
        else:  # If filename is just in the current directory
            os.makedirs(".", exist_ok=True)

        self.filename = filename
        self.file = open(self.filename, "w", newline="")
        self.writer = csv.writer(self.file)
        # Write header
        self.writer.writerow(
            ["time_s", "frame_index_device", "pressure_mmHg"]
        )  # Clarified header names
        self.is_recording = True
        log.info(f"CSVRecorder started for {self.filename}")

    def write_data(self, t, frame_idx, pressure):
        if self.is_recording:
            self.writer.writerow([f"{t:.6f}", frame_idx, f"{pressure:.6f}"])

    def stop(self):
        if not self.is_recording:
            return
        try:
            self.file.close()
        except Exception as e:
            log.error(f"Error closing CSV file {self.filename}: {e}")
        self.is_recording = False
        log.info(f"Stopped CSV recording for {self.filename}")


class TrialRecorder:
    """
    Manages video recording (using SimpleVideoRecorder) and CSV data recording.
    """

    def __init__(self, basepath, fps, frame_size, video_ext="avi", video_codec="MJPG"):
        # frame_size is kept for compatibility but SimpleVideoRecorder might not strictly need it for imageio
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.base_filename_with_timestamp = f"{basepath}_{ts}"
        self.is_recording_active = False

        log.info(
            f"Initializing TrialRecorder with base: {self.base_filename_with_timestamp}, format: {video_ext}, codec: {video_codec}, fps: {fps}"
        )

        try:
            # Video recorder
            self.video_recorder = SimpleVideoRecorder(
                self.base_filename_with_timestamp,  # Will append .avi or .tif
                fps,
                video_ext=video_ext,
                video_codec=video_codec,
                frame_size=frame_size,  # Pass frame_size, though imageio might not use it
            )
            log.info(
                f"Initialized SimpleVideoRecorder for: {self.video_recorder.out_path}"
            )

            # CSV recorder
            csv_filepath = self.base_filename_with_timestamp + ".csv"
            self.csv_recorder = CSVRecorder(csv_filepath)
            log.info(f"Initialized CSVRecorder for: {csv_filepath}")

            self.is_recording_active = True
        except Exception as e:
            log.exception(f"Error initializing TrialRecorder: {e}")
            # Clean up partially initialized recorders if any
            if hasattr(self, "video_recorder") and self.video_recorder:
                self.video_recorder.stop()
            if hasattr(self, "csv_recorder") and self.csv_recorder:
                self.csv_recorder.stop()
            self.is_recording_active = False
            raise  # Re-raise the exception so MainWindow knows initialization failed

    def write_video_frame(self, frame_numpy):
        if self.is_recording_active and self.video_recorder:
            try:
                self.video_recorder.write_frame(frame_numpy)
            except Exception as e:
                log.error(f"Error writing video frame: {e}")
                # Consider how to handle write errors, e.g., stop recording, notify user.

    def write_csv_data(self, t, frame_idx, pressure):
        if self.is_recording_active and self.csv_recorder:
            try:
                self.csv_recorder.write_data(t, frame_idx, pressure)
            except Exception as e:
                log.error(f"Error writing CSV data: {e}")

    def stop(self):
        if not self.is_recording_active:
            log.info("TrialRecorder stop called, but not active.")
            return

        log.info("Stopping TrialRecorder...")
        if hasattr(self, "video_recorder") and self.video_recorder:
            self.video_recorder.stop()
        if hasattr(self, "csv_recorder") and self.csv_recorder:
            self.csv_recorder.stop()

        self.is_recording_active = False
        frames_written = (
            getattr(self.video_recorder, "frames_written", "N/A")
            if hasattr(self, "video_recorder")
            else "N/A"
        )
        log.info(f"TrialRecorder stopped. Video frames: {frames_written}")

    @property
    def is_recording(self):
        return self.is_recording_active

    @property
    def video_frame_count(self):
        if hasattr(self, "video_recorder") and self.video_recorder:
            return self.video_recorder.frames_written
        return 0
