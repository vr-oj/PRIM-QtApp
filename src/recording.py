import cv2
import csv
import os
import time
import logging
import queue # Added
from threading import Thread # Added
from config import DEFAULT_VIDEO_CODEC, DEFAULT_VIDEO_EXTENSION

log = logging.getLogger(__name__)

class VideoRecorder:
    def __init__(self, filename, fourcc=DEFAULT_VIDEO_CODEC, fps=30, frame_size=(640,480)):
        os.makedirs(os.path.dirname(filename) or '.', exist_ok=True)
        name, _ = os.path.splitext(filename)
        effective_extension = DEFAULT_VIDEO_EXTENSION
        self.filename = f"{name}.{effective_extension}"
        try:
            self.writer = cv2.VideoWriter(
                self.filename, cv2.VideoWriter_fourcc(*fourcc), fps, frame_size
            )
            self.frame_count = 0
            self.is_recording = True # Indicates successful initialization
            log.info(f"VideoRecorder started for {self.filename} with codec {fourcc}, {fps}fps, {frame_size}")
        except Exception as e:
            log.error(f"Failed to initialize VideoWriter for {self.filename}: {e}")
            self.writer = None
            self.is_recording = False

    def write_frame(self, frame):
        if self.is_recording and self.writer:
            try:
                self.writer.write(frame)
                self.frame_count += 1
            except Exception as e:
                log.error(f"Error writing video frame: {e}")
                self.stop()

    def stop(self):
        if self.writer: # Check if writer was ever initialized
            log.info(f"Stopping video recording for {self.filename}. Total frames: {self.frame_count}")
            self.writer.release()
        self.is_recording = False
        self.writer = None

class CSVRecorder:
    def __init__(self, filename, fieldnames=('time_s', 'frame_idx', 'pressure_mmHg')):
        os.makedirs(os.path.dirname(filename) or '.', exist_ok=True)
        self.filename = filename
        try:
            self.file = open(self.filename, 'w', newline='')
            self.writer = csv.DictWriter(self.file, fieldnames=fieldnames)
            self.writer.writeheader()
            self.is_recording = True # Indicates successful initialization
            log.info(f"CSVRecorder started for {self.filename}")
        except Exception as e:
            log.error(f"Failed to initialize CSVWriter for {self.filename}: {e}")
            self.file = None
            self.writer = None
            self.is_recording = False

    def write_data(self, time_s, frame_idx, pressure):
        if self.is_recording and self.writer:
            try:
                self.writer.writerow({'time_s': time_s, 'frame_idx': frame_idx, 'pressure_mmHg': pressure})
                # self.file.flush() # CRITICAL: REMOVED this for performance
            except Exception as e:
                log.error(f"Error writing CSV data: {e}")
                self.stop()

    def stop(self):
        if self.file: # Check if file was ever opened
            log.info(f"Stopping CSV recording for {self.filename}")
            self.file.close() # Close will flush remaining data
        self.is_recording = False
        self.file = None
        self.writer = None

class TrialRecorder:
    def __init__(self, basepath, fps, frame_size, video_codec=DEFAULT_VIDEO_CODEC, video_ext=DEFAULT_VIDEO_EXTENSION):
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.basepath_with_ts = f"{basepath}_{ts}"
        
        video_filename = f"{self.basepath_with_ts}.{video_ext}"
        csv_filename = f"{self.basepath_with_ts}.csv"

        self._video_recorder_args = (video_filename, video_codec, fps, frame_size)
        self._csv_recorder_args = (csv_filename,)
        
        self.video = None
        self.csv = None
        self._initialization_successful = False # Flag for worker thread status

        self._queue = queue.Queue(maxsize=200) # Increased maxsize, adjust as needed
        self._recording_active_flag = False 
        self._worker_thread = None
        # Worker thread is started by calling start_recording() method
        
    def start_recording_session(self):
        """Starts the worker thread and initializes recorders."""
        if self._worker_thread is None:
            self._recording_active_flag = True
            self._worker_thread = Thread(target=self._process_queue, daemon=True)
            self._worker_thread.start()
            log.info("TrialRecorder worker thread initiated.")
            # Note: Initialization of self.video and self.csv happens in the worker.
            # The is_recording property will reflect success after a short delay.
            return True
        return False


    def _process_queue(self):
        try:
            v_fn, v_codec, v_fps, v_fs = self._video_recorder_args
            temp_video_recorder = VideoRecorder(v_fn, fourcc=v_codec, fps=v_fps, frame_size=v_fs)
            
            c_fn, = self._csv_recorder_args
            temp_csv_recorder = CSVRecorder(c_fn)

            if temp_video_recorder.is_recording or temp_csv_recorder.is_recording:
                self.video = temp_video_recorder
                self.csv = temp_csv_recorder
                self._initialization_successful = True
                log.info("Video and/or CSV recorders initialized successfully in worker thread.")
            else:
                log.error("TrialRecorder: Neither video nor CSV recorder initialized successfully in worker.")
                self._initialization_successful = False
                self._recording_active_flag = False # Stop if recorders failed
                return 

        except Exception as e:
            log.error(f"TrialRecorder: Exception initializing recorders in worker thread: {e}", exc_info=True)
            self._initialization_successful = False
            self._recording_active_flag = False
            return

        while self._recording_active_flag or not self._queue.empty():
            try:
                item_type, data = self._queue.get(timeout=0.1)
                if item_type == "video" and self.video and self.video.is_recording:
                    self.video.write_frame(data)
                elif item_type == "csv" and self.csv and self.csv.is_recording:
                    self.csv.write_data(*data)
                self._queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                log.error(f"TrialRecorder: Error processing queue item: {e}", exc_info=True)
                # Consider whether to stop recording on such errors or just log.
                # For now, it logs and continues.

        if self.video: self.video.stop()
        if self.csv: self.csv.stop()
        log.info("TrialRecorder worker thread finished processing and cleaned up recorders.")

    def write_video_frame(self, frame):
        if self._recording_active_flag and self._initialization_successful:
            try:
                self._queue.put_nowait(("video", frame))
            except queue.Full:
                log.warning("TrialRecorder video queue full. Frame dropped.")

    def write_csv_data(self, t, frame_idx, p):
        if self._recording_active_flag and self._initialization_successful:
            try:
                self._queue.put_nowait(("csv", (t, frame_idx, p)))
            except queue.Full:
                log.warning("TrialRecorder CSV queue full. Data point dropped.")

    def stop(self):
        log.info("TrialRecorder stop method called.")
        self._recording_active_flag = False
        if self._worker_thread and self._worker_thread.is_alive():
            log.info("Waiting for TrialRecorder worker thread to join...")
            # Ensure queue is empty or timeout occurs
            # self._queue.join() # This can block indefinitely if worker died before emptying
            self._worker_thread.join(timeout=5.0)
            if self._worker_thread.is_alive():
                log.warning("TrialRecorder worker thread did not join in time.")
        self._worker_thread = None
        log.info(f"Trial recording stopped for base: {self.basepath_with_ts}")
        # Recorders are stopped by the worker thread itself upon loop exit.

    @property
    def video_frame_count(self):
        return self.video.frame_count if self.video and hasattr(self.video, 'frame_count') else 0
        
    @property
    def is_recording(self):
        """Indicates if the recording session is active and was initialized successfully."""
        return self._recording_active_flag and self._initialization_successful