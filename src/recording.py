import cv2
import csv
import os
import time
import logging # Added for logging
from config import DEFAULT_VIDEO_CODEC, DEFAULT_VIDEO_EXTENSION # Added for config
from tifffile import TiffWriter

log = logging.getLogger(__name__) # Added for logging

class VideoRecorder:
    def __init__(self, filename, fourcc=DEFAULT_VIDEO_CODEC, fps=30, frame_size=(640,480)): # Modified default fourcc
        os.makedirs(os.path.dirname(filename) or '.', exist_ok=True)
        name, _ = os.path.splitext(filename)
        effective_extension = DEFAULT_VIDEO_EXTENSION
        self.filename = f"{name}.{effective_extension}"

        try:
            self.writer = cv2.VideoWriter(
                self.filename,
                cv2.VideoWriter_fourcc(*fourcc),
                fps,
                frame_size
            )
            if not self.writer.isOpened():
                log.error(f"Failed to open VideoWriter for {self.filename}")
                self.is_recording = False
                self.writer = None
                return
            
            self.frame_count = 0
            self.is_recording = True
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
                self.stop() # Stop recording on error

    def stop(self):
        if self.is_recording and self.writer:
            log.info(f"Stopping video recording for {self.filename}. Total frames: {self.frame_count}")
            self.writer.release()
        self.is_recording = False
        self.writer = None # Ensure it's reset

class CSVRecorder:
    def __init__(self, filename, fieldnames=('time_s', 'frame_idx', 'pressure_mmHg')): # Modified fieldnames for clarity
        os.makedirs(os.path.dirname(filename) or '.', exist_ok=True)
        self.filename = filename
        try:
            self.file = open(self.filename, 'w', newline='')
            self.writer = csv.DictWriter(self.file, fieldnames=fieldnames)
            self.writer.writeheader()
            self.is_recording = True
            log.info(f"CSVRecorder started for {self.filename}")
        except Exception as e:
            log.error(f"Failed to initialize CSVWriter for {self.filename}: {e}")
            self.file = None
            self.writer = None
            self.is_recording = False

    def write_data(self, time_s, frame_idx, pressure): # Renamed method for clarity
        if self.is_recording and self.writer:
            try:
                self.writer.writerow({'time_s': time_s, 'frame_idx': frame_idx, 'pressure_mmHg': pressure})
                self.file.flush() # Ensure data is written to disk
            except Exception as e:
                log.error(f"Error writing CSV data: {e}")
                self.stop() # Stop recording on error


    def stop(self):
        if self.is_recording and self.file:
            log.info(f"Stopping CSV recording for {self.filename}")
            self.file.close()
        self.is_recording = False
        self.file = None
        self.writer = None


class TrialRecorder:
    def __init__(self, basepath, fps, frame_size,
                 video_codec=DEFAULT_VIDEO_CODEC,
                 video_ext=DEFAULT_VIDEO_EXTENSION):
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.basepath_with_ts = f"{basepath}_{ts}"

        # Decide on filename & recorder class based on extension
        if video_ext.lower() in ('tif', 'tiff'):
            # full-res TIFF stack
            tif_filename = f"{self.basepath_with_ts}.tif"
            self.video = TiffStackRecorder(tif_filename, frame_shape=frame_size)
        else:
            # AVI or other compressed video
            vid_filename = f"{self.basepath_with_ts}.{video_ext}"
            self.video = VideoRecorder(
                vid_filename,
                fourcc=video_codec,
                fps=fps,
                frame_size=frame_size
            )

        # still record CSV alongside
        csv_filename = f"{self.basepath_with_ts}.csv"
        self.csv = CSVRecorder(csv_filename)


    def write_video_frame(self, frame): # Separate method for video
        if self.video:
            self.video.write_frame(frame)

    def write_csv_data(self, t, frame_idx, p): # Separate method for CSV data
        if self.csv:
            self.csv.write_data(t, frame_idx, p)

    def stop(self):
        if self.video:
            self.video.stop()
        if self.csv:
            self.csv.stop()
        log.info(f"Trial recording stopped for base: {self.basepath_with_ts}")

    @property
    def video_frame_count(self):
        if not self.video:
            return 0
        return getattr(self.video, 'frame_count', 0)
        
    @property
    def is_recording(self):
        # Considered recording if either video or CSV (or both) are active
        # More precisely, if they were successfully initialized.
        return (self.video and self.video.is_recording) or \
               (self.csv and self.csv.is_recording)
    

class TiffStackRecorder:
    def __init__(self, filename, frame_shape):
        # ensure output directory exists
        os.makedirs(os.path.dirname(filename) or '.', exist_ok=True)
        base, _ = os.path.splitext(filename)
        self.filename = base + '.tif'
        self._writer = TiffWriter(self.filename, bigtiff=True)
        self.is_recording = True
        self.frame_count = 0
        log.info(f"TiffStackRecorder started for {self.filename}")

    def write_frame(self, frame):
        # frame is BGR; convert to RGB
        rgb = frame[..., ::-1]
        self._writer.write(rgb, photometric='rgb')
        self.frame_count += 1

    def stop(self):
        if self.is_recording:
            self._writer.close()
            self.is_recording = False
            log.info(f"Stopping TIFF recording for {self.filename}. Total frames: {self.frame_count}")
