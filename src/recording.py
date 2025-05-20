import os
import time
import logging
from threads.recording_thread import RecordingThread

log = logging.getLogger(__name__)  # Ensure logger is configured elsewhere


class TrialRecorder:
    """
    Manages background writing of TIFF stacks and CSV data
    using RecordingThread to keep the GUI and plot smooth.
    """

    def __init__(
        self, basepath, fps, frame_size=None, video_ext="tif", video_codec=None
    ):
        # Timestamped base name (no extension)
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.base = f"{basepath}_{ts}"

        # Ensure output directory exists
        out_dir = os.path.dirname(self.base) or "."
        os.makedirs(out_dir, exist_ok=True)

        # Filenames for TIFF and CSV
        tiff_name = os.path.basename(self.base) + ".tif"
        csv_name = os.path.basename(self.base) + ".csv"

        # Launch the background recording thread
        try:
            self.rec_thread = RecordingThread(
                out_dir=out_dir, tiff_name=tiff_name, csv_name=csv_name, fps=fps
            )
            self.rec_thread.error.connect(self._on_recording_error)
            self.rec_thread.start()
            self.is_recording_active = True
            log.info(f"RecordingThread started: {tiff_name}, {csv_name}")
        except Exception as e:
            log.exception(f"Failed to start RecordingThread: {e}")
            self.is_recording_active = False
            raise

    def write_video_frame(self, frame_numpy):
        """
        Enqueue a video frame for background TIFF writing.
        (frame_index isn’t needed for TIFF stacks, so we pass None.)
        """
        if self.is_recording_active:
            self.rec_thread.enqueue_frame(None, frame_numpy)

    def write_csv_data(self, t, frame_idx, pressure):
        """
        Enqueue a CSV data row (timestamp, frame index, pressure).
        """
        if self.is_recording_active:
            self.rec_thread.enqueue_data(t, frame_idx, pressure)

    def stop(self):
        """
        Tell the recording thread to finish and wait for it.
        """
        if not getattr(self, "is_recording_active", False):
            log.info("TrialRecorder.stop() called but recording was not active.")
            return

        log.info("Stopping RecordingThread …")
        self.rec_thread.stop()
        self.is_recording_active = False
        log.info("RecordingThread stopped successfully.")

    def _on_recording_error(self, msg):
        """
        Handle any errors emitted by RecordingThread.
        """
        log.error(f"RecordingThread error: {msg}")

    @property
    def video_frame_count(self):
        """
        Expose how many TIFF frames were written,
        so main_window can report it.
        """
        return getattr(self.rec_thread, "frames_written", 0)
