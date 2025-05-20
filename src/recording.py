import os
import time
import csv
import logging
import imageio  # For AVI and potentially other formats
import tifffile  # For TIFF stacks

log = logging.getLogger(__name__)  # Make sure logger is defined


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
            # imageio uses ffmpeg for AVI. Common codecs: 'mjpeg', 'libx264'
            # 'MJPG' from your config.py should work if ffmpeg is properly installed with imageio-ffmpeg.
            # The 'quality' parameter is for lossy codecs like MJPEG (0-10, 10 is best)
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

    def write_frame(self, frame_numpy):  # Expects a numpy array
        if self.video_ext == "avi" and self.writer:
            self.writer.append_data(frame_numpy)
        elif self.video_ext in ("tif", "tiff"):
            # For the first frame, 'append' should be False.
            # For subsequent frames, append must be True.
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
