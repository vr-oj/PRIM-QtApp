import os
import time
import csv
import logging
import threading
import imageio

try:
    from pycromanager import Bridge
except ImportError:
    Bridge = None  # If pycromanager or Bridge is not found, set Bridge to None


log = logging.getLogger(__name__)


class CSVRecorder:
    """
    Records timestamped data (time, frame index, pressure) to a CSV file.
    """

    def __init__(self, filename):
        os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)
        self.filename = filename
        self.file = open(self.filename, "w", newline="")
        self.writer = csv.writer(self.file)
        # Write header
        self.writer.writerow(["time", "frame_index", "pressure"])
        self.is_recording = True
        log.info(f"CSVRecorder started for {self.filename}")

    def write_data(self, t, frame_idx, pressure):
        if self.is_recording:
            self.writer.writerow([f"{t:.6f}", frame_idx, f"{pressure:.6f}"])

    def stop(self):
        if not self.is_recording:
            return
        self.file.close()
        self.is_recording = False
        log.info(f"Stopped CSV recording for {self.filename}")


class MMRecorder:
    """
    Uses pycromanager to grab continuous frames from a µManager-configured camera and writes to MP4 via imageio.
    """

    def __init__(self, out_path, fps, frame_size):
        # Initialize bridge to µManager
        self.bridge = Bridge()
        self.mmcore = self.bridge.get_core()
        self.out_path = f"{out_path}.mp4"
        self.fps = fps
        self.frame_size = frame_size  # (width, height)
        self._stop_event = threading.Event()
        self.frame_count = 0
        self.is_recording = False
        self.thread = None

    def start(self):
        self.is_recording = True
        self.thread = threading.Thread(target=self._acquire_loop, daemon=True)
        self.thread.start()

    def _acquire_loop(self):
        # Start continuous acquisition
        self.mmcore.startContinuousSequenceAcquisition(0)
        writer = imageio.get_writer(self.out_path, fps=self.fps, codec="libx264")
        try:
            while not self._stop_event.is_set():
                tagged = self.bridge.get_tagged_image()
                # reshape flat pixel array to (height, width)
                img = tagged.pix.reshape(self.frame_size[1], self.frame_size[0])
                writer.append_data(img)
                self.frame_count += 1
        finally:
            writer.close()
            self.mmcore.stopSequenceAcquisition()

    def stop(self):
        if not self.is_recording:
            return
        self._stop_event.set()
        if self.thread:
            self.thread.join()
        self.is_recording = False
        log.info(
            f"Stopped µManager recording: {self.out_path} (frames: {self.frame_count})"
        )


class TrialRecorder:
    def __init__(self, basepath, fps, frame_size, video_codec=None, video_ext="avi"):
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.basepath_with_ts = f"{basepath}_{ts}"

        # ─── Video recorder ────────────────────
        if Bridge is not None:
            # use µManager
            try:
                self.video = MMRecorder(self.basepath_with_ts, fps, frame_size)
                self.video.start()
                log.info("Started µManager video recording")
            except Exception as e:
                log.error(f"µManager recording failed: {e}", exc_info=True)
                log.info("Falling back to OpenCV recorder")
                self.video = CV2Recorder(
                    self.basepath_with_ts + f".{video_ext}",
                    fps,
                    frame_size,
                    codec=video_codec,
                )
                self.video.start()
        else:
            # no µManager available → use OpenCV
            log.info("pycromanager Bridge not available, using OpenCV recorder")
            self.video = CV2Recorder(
                self.basepath_with_ts + f".{video_ext}",
                fps,
                frame_size,
                codec=video_codec,
            )
            self.video.start()

        # ─── CSV recorder ──────────────────────
        csv_filename = f"{self.basepath_with_ts}.csv"
        self.csv = CSVRecorder(csv_filename)

    def write_csv_data(self, t, frame_idx, pressure):
        """
        Called by the main loop to log sensor data.
        """
        self.csv.write_data(t, frame_idx, pressure)

    def write_video_frame(self, frame=None):
        """
        No-op: MMRecorder streams autonomously.
        """
        pass

    def stop(self):
        # Stop video and CSV
        if self.video:
            self.video.stop()
        if self.csv:
            self.csv.stop()

    @property
    def is_recording(self):
        return bool(self.video and self.video.is_recording)

    @property
    def video_frame_count(self):
        return getattr(self.video, "frame_count", 0)
