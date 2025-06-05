import os
import time
import csv
import logging
import imageio  # For AVI and potentially other formats
import tifffile  # For TIFF stacks
import queue
from PyQt5.QtCore import QThread

log = logging.getLogger(__name__)


class RecordingWorker(QThread):
    def __init__(self, basepath, fps, frame_size, video_ext, video_codec, parent=None):
        super().__init__(parent)
        self.basepath = basepath
        self.fps = fps
        self.frame_size = frame_size
        self.video_ext = video_ext
        self.video_codec = video_codec

        self.trial_recorder = None  # Initialize to None
        self.data_queue = queue.Queue()
        self._is_running = False  # Indicates the main processing loop should run
        self.video_frame_count_internal = 0

    def run(self):
        # Phase 1: Initialize TrialRecorder
        try:
            self.trial_recorder = TrialRecorder(
                basepath=self.basepath,
                fps=self.fps,
                frame_size=self.frame_size,
                video_ext=self.video_ext,
                video_codec=self.video_codec,
            )
            # TrialRecorder's __init__ sets is_recording_active or raises an exception.
            if not self.trial_recorder.is_recording_active:
                # This case should ideally be covered if TrialRecorder.init raises an error on failure.
                # However, as a safeguard:
                log.error("TrialRecorder initialized but did not report as active.")
                if hasattr(self.trial_recorder, "stop"):  # Attempt cleanup
                    self.trial_recorder.stop()
                self.trial_recorder = None  # Ensure it's None for is_ready_to_record
                return  # Worker thread terminates

            log.info(
                f"RecordingWorker's TrialRecorder initialized successfully for {self.basepath}"
            )
            self._is_running = (
                True  # Signal that initialization is complete and loop can run
            )

        except Exception as e:
            log.exception(
                f"CRITICAL: Failed to initialize TrialRecorder in RecordingWorker's setup: {e}"
            )
            self.trial_recorder = None  # Ensure trial_recorder is None
            # self._is_running remains False (its default from __init__)
            return  # Worker thread terminates, is_ready_to_record will be false

        # Phase 2: Main processing loop (only if initialization was successful)
        try:
            log.info(f"RecordingWorker processing loop started for {self.basepath}.")
            while (
                True
            ):  # Loop controlled by _is_running and queue status checked inside
                try:
                    # Check running state before blocking on get, or handle stop more gracefully
                    if not self._is_running and self.data_queue.empty():
                        log.debug(
                            "RecordingWorker: Not running and queue empty, exiting loop."
                        )
                        break

                    item_type, data = self.data_queue.get(
                        timeout=0.1
                    )  # Timeout allows checking _is_running

                    if item_type == "stop":
                        log.debug("RecordingWorker: Stop sentinel received in queue.")
                        self._is_running = (
                            False  # Signal to exit loop after queue is drained
                        )
                        self.data_queue.task_done()  # Acknowledge the stop item
                        if self.data_queue.empty():  # If queue is now empty, break
                            break
                        continue  # Else, continue to drain the queue

                    # Process data if trial_recorder is valid (it should be if we reached here)
                    if self.trial_recorder:
                        if item_type == "video":
                            self.trial_recorder.write_video_frame(data)
                            # Update internal count directly from the source of truth
                            if (
                                hasattr(self.trial_recorder, "video_recorder")
                                and self.trial_recorder.video_recorder
                            ):
                                self.video_frame_count_internal = (
                                    self.trial_recorder.video_recorder.frames_written
                                )
                        elif item_type == "csv":
                            t, idx, p = data
                            self.trial_recorder.write_csv_data(t, idx, p)
                    else:
                        # This should not happen if _is_running is managed correctly post-initialization
                        log.warning(
                            "RecordingWorker: trial_recorder is None in processing loop. Forcing stop."
                        )
                        self._is_running = False

                    self.data_queue.task_done()

                except queue.Empty:
                    # Timeout occurred, loop continues to check self._is_running
                    if not self._is_running and self.data_queue.empty():
                        log.debug(
                            "RecordingWorker: Exiting loop (timeout) - not running and queue empty."
                        )
                        break  # Exit if signaled to stop and queue is now confirmed empty
                    continue
                except Exception as e:
                    log.exception(
                        f"Error processing item from queue in RecordingWorker: {e}"
                    )
                    # Consider if a single item processing error should stop the whole recording
                    # For now, it continues, but logs the error.
        finally:
            # This finally block is for the main processing loop
            log.debug("RecordingWorker: Reached finally block of processing loop.")
            if self.trial_recorder:
                log.info(
                    "RecordingWorker: Stopping internal TrialRecorder from loop's finally block."
                )
                self.trial_recorder.stop()
                # Update frame count one last time from the definitive source
                if (
                    hasattr(self.trial_recorder, "video_recorder")
                    and self.trial_recorder.video_recorder
                ):
                    self.video_frame_count_internal = (
                        self.trial_recorder.video_recorder.frames_written
                    )

            log.info("RecordingWorker run method finished completely.")
            self._is_running = (
                False  # Ensure flag is definitively false on exit from the run method
            )

    def add_video_frame(self, frame_numpy):
        # Only add if the worker's main loop is intended to be running.
        # The check for self.trial_recorder's existence happens implicitly
        # by self._is_running being True only after successful init.
        if self._is_running:
            self.data_queue.put(("video", frame_numpy))
        else:
            log.warning(
                "RecordingWorker: add_video_frame called but worker is not running."
            )

    def add_csv_data(self, t, idx, p):
        if self._is_running:
            self.data_queue.put(("csv", (t, idx, p)))
        else:
            log.warning(
                "RecordingWorker: add_csv_data called but worker is not running."
            )

    def stop_worker(self):
        log.info("RecordingWorker: stop_worker method called.")
        # This method signals the run() loop to stop and then drain the queue.
        # It doesn't wait for the thread to finish here.
        if self._is_running:  # If it was set to run (i.e., init was successful)
            log.debug(
                "RecordingWorker: Queuing stop sentinel because worker was running."
            )
            self.data_queue.put(("stop", None))
        else:
            log.debug(
                "RecordingWorker: stop_worker called, but worker was not marked as running (or already stopping)."
            )
        # self._is_running will be set to False by the run loop when it processes the stop signal or exits.
        # Or, if stop_worker is called before run() even sets _is_running to True (e.g. very fast stop),
        # it's already false.

    @property
    def video_frame_count(self):
        # Prioritize the direct source if available
        if (
            self.trial_recorder
            and hasattr(self.trial_recorder, "video_recorder")
            and self.trial_recorder.video_recorder
        ):
            return self.trial_recorder.video_recorder.frames_written
        return (
            self.video_frame_count_internal
        )  # Fallback to the last known internal count

    @property
    def is_ready_to_record(self):
        # This property is checked by MainWindow *after* starting the thread.
        # It reflects if TrialRecorder was successfully initialized and is active.
        return (
            self.trial_recorder is not None and self.trial_recorder.is_recording_active
        )


class SimpleVideoRecorder:
    def __init__(
        self, out_path, fps, video_ext="avi", video_codec="MJPG", frame_size=None
    ):
        self.out_path = f"{out_path}.{video_ext.lower()}"
        self.fps = fps
        self.video_ext = video_ext.lower()
        self.writer = None
        self.frames_written = 0

        dirname = os.path.dirname(self.out_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        else:
            os.makedirs(".", exist_ok=True)

        try:
            if self.video_ext == "avi":
                self.writer = imageio.get_writer(
                    self.out_path, fps=self.fps, codec=video_codec, quality=8
                )
            elif self.video_ext in ("tif", "tiff"):
                pass  # tifffile handles file creation on first write
            else:
                log.error(f"Unsupported video extension: {self.video_ext}")
                raise ValueError(f"Unsupported video extension: {self.video_ext}")
            log.info(f"SimpleVideoRecorder initialized for {self.out_path}")
        except Exception as e:
            log.error(
                f"Failed to initialize imageio.get_writer for {self.out_path} with codec {video_codec}: {e}"
            )
            raise  # Re-raise the exception to be caught by TrialRecorder or RecordingWorker

    def write_frame(self, frame_numpy):
        try:
            if self.video_ext == "avi" and self.writer:
                self.writer.append_data(frame_numpy)
            elif self.video_ext in ("tif", "tiff"):
                tifffile.imwrite(
                    self.out_path, frame_numpy, append=(self.frames_written > 0)
                )
            else:
                log.warning(
                    f"Attempted to write frame for unsupported/uninitialized recorder: {self.video_ext}"
                )
                return
            self.frames_written += 1
        except Exception as e:
            log.error(f"Error writing frame to {self.out_path}: {e}")
            # Consider how to handle this, e.g., raise an error to stop recording
            raise

    def stop(self):
        if self.writer and self.video_ext == "avi":
            try:
                self.writer.close()
            except Exception as e:
                log.error(f"Error closing AVI writer for {self.out_path}: {e}")
        self.writer = None
        log.info(
            f"Stopped SimpleVideoRecorder for {self.out_path} ({self.frames_written} frames)"
        )


class CSVRecorder:
    def __init__(self, filename):
        dirname = os.path.dirname(filename)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        else:
            os.makedirs(".", exist_ok=True)

        self.filename = filename
        try:
            self.file = open(self.filename, "w", newline="")
            self.writer = csv.writer(self.file)
            self.writer.writerow(["time_s", "frame_index_device", "pressure_mmHg"])
            self.is_recording = (
                True  # Different from TrialRecorder's is_recording_active
            )
            log.info(f"CSVRecorder started for {self.filename}")
        except Exception as e:
            log.error(f"Failed to initialize CSVRecorder for {self.filename}: {e}")
            self.is_recording = False
            raise

    def write_data(self, t, frame_idx, pressure):
        if self.is_recording:
            try:
                self.writer.writerow([f"{t:.6f}", frame_idx, f"{pressure:.6f}"])
            except Exception as e:
                log.error(f"Error writing data to CSV {self.filename}: {e}")
                # Consider implications, e.g. stop recording or mark as failed
                raise

    def stop(self):
        if not self.is_recording:  # Check if it was ever successfully recording
            if hasattr(self, "file") and self.file and not self.file.closed:
                # If file was opened but is_recording became false due to error
                try:
                    self.file.close()
                except Exception as e:
                    log.error(
                        f"Error closing CSV file (already stopped) {self.filename}: {e}"
                    )
            return

        try:
            if hasattr(self, "file") and self.file:  # Check if file attribute exists
                self.file.close()
        except Exception as e:
            log.error(f"Error closing CSV file {self.filename}: {e}")
        finally:  # Ensure is_recording is set to false
            self.is_recording = False
            log.info(f"Stopped CSV recording for {self.filename}")


class TrialRecorder:
    def __init__(self, basepath, fps, frame_size, video_ext="avi", video_codec="MJPG"):
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.base_filename_with_timestamp = f"{basepath}_{ts}"  # Used by sub-recorders
        self.is_recording_active = False  # This will be set to True on successful init
        self.video_recorder = None
        self.csv_recorder = None

        log.info(
            f"Initializing TrialRecorder with base: {self.base_filename_with_timestamp}, format: {video_ext}, codec: {video_codec}, fps: {fps}"
        )

        try:
            self.video_recorder = SimpleVideoRecorder(
                self.base_filename_with_timestamp,  # SimpleVideoRecorder appends extension
                fps,
                video_ext=video_ext,
                video_codec=video_codec,
                frame_size=frame_size,
            )
            log.info(
                f"TrialRecorder: Initialized SimpleVideoRecorder for: {self.video_recorder.out_path}"
            )

            csv_filepath = self.base_filename_with_timestamp + ".csv"
            self.csv_recorder = CSVRecorder(csv_filepath)
            log.info(f"TrialRecorder: Initialized CSVRecorder for: {csv_filepath}")

            self.is_recording_active = True  # Signal successful initialization
            log.info("TrialRecorder initialization successful and active.")

        except Exception as e:
            log.exception(f"CRITICAL: Error during TrialRecorder initialization: {e}")
            # Cleanup partially initialized recorders if any
            if self.video_recorder:  # video_recorder might be set even if csv failed
                self.video_recorder.stop()
            if (
                self.csv_recorder
            ):  # csv_recorder might be set if video succeeded but it failed
                self.csv_recorder.stop()
            self.is_recording_active = False  # Ensure it's false on failure
            raise  # Re-raise the exception to be caught by RecordingWorker

    def write_video_frame(self, frame_numpy):
        if self.is_recording_active and self.video_recorder:
            try:
                self.video_recorder.write_frame(frame_numpy)
            except Exception as e:
                log.error(
                    f"TrialRecorder: Error writing video frame via SimpleVideoRecorder: {e}"
                )
                # Consider stopping recording if a sub-recorder fails critically
                # self.stop() # Example: stop all on critical error
                # self.is_recording_active = False
                # raise # Or re-raise to be handled by RecordingWorker

    def write_csv_data(self, t, frame_idx, pressure):
        if self.is_recording_active and self.csv_recorder:
            try:
                self.csv_recorder.write_data(t, frame_idx, pressure)
            except Exception as e:
                log.error(f"TrialRecorder: Error writing CSV data via CSVRecorder: {e}")
                # self.stop()
                # self.is_recording_active = False
                # raise

    def stop(self):
        if not self.is_recording_active:
            # This might be called if init failed and then stop is called again in a finally block
            log.info("TrialRecorder stop called, but was not (or is no longer) active.")
            # Still attempt to stop sub-recorders if they exist, as they might have been partially created
            if hasattr(self, "video_recorder") and self.video_recorder:
                self.video_recorder.stop()
            if hasattr(self, "csv_recorder") and self.csv_recorder:
                self.csv_recorder.stop()
            return

        log.info("TrialRecorder: Stopping active recording...")
        if self.video_recorder:
            self.video_recorder.stop()
        if self.csv_recorder:
            self.csv_recorder.stop()

        self.is_recording_active = False  # Mark as no longer active
        frames_written_str = "N/A"
        if self.video_recorder and hasattr(self.video_recorder, "frames_written"):
            frames_written_str = str(self.video_recorder.frames_written)

        log.info(f"TrialRecorder stopped. Video frames recorded: {frames_written_str}")

    @property
    def is_recording(
        self,
    ):  # Kept for compatibility if used elsewhere, but is_recording_active is the source of truth
        return self.is_recording_active

    @property
    def video_frame_count(self):
        if self.video_recorder and hasattr(self.video_recorder, "frames_written"):
            return self.video_recorder.frames_written
        return 0
