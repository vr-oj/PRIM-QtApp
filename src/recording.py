import cv2
import csv
import os
import time
import logging
import imageio
import subprocess, shlex
from config import DEFAULT_VIDEO_CODEC, DEFAULT_VIDEO_EXTENSION # Added for config
from tifffile import TiffWriter

log = logging.getLogger(__name__) # Added for logging

class FFmpegRecorder:
    """
    Spawns an FFmpeg process to capture directly from a DSHOW camera.
    """
    def __init__(self, device_name, out_path, fps, frame_size):
        width, height = frame_size
        # build a command that uses the DirectShow video= device
        cmd = (
            f'ffmpeg -y '
            f'-f dshow '
            f'-video_size {width}x{height} '
            f'-framerate {fps} '
            f'-i video="{device_name}" '
            f'-c:v libx264 '
            f'-pix_fmt yuv420p '
            f'"{out_path}.mp4"'
        )
        log.info(f"Starting FFmpeg capture: {cmd}")
        # launch FFmpeg; it will record until we kill it
        self.proc = subprocess.Popen(shlex.split(cmd), stdin=subprocess.DEVNULL)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            log.info("Stopping FFmpeg capture")
            # CTRL+C event will tell ffmpeg to finalize the file
            self.proc.send_signal(subprocess.signal.CTRL_C_EVENT)
            self.proc.wait()

class VideoRecorder:
    def __init__(self, filename, fourcc, fps, frame_size):
        os.makedirs(os.path.dirname(filename) or '.', exist_ok=True)
        name, _ = os.path.splitext(filename)
        self.filename = f"{name}.avi"
        self.frame_count = 0
        self.is_recording = False

        # 1) Try OpenCV writer first
        self.writer = cv2.VideoWriter(
            self.filename,
            cv2.VideoWriter_fourcc(*fourcc),
            fps,
            frame_size
        )
        log.info(f"OpenCV VideoWriter.isOpened()? {self.writer.isOpened()}")

        # 2) If that failed, fall back to imageio
        if not getattr(self.writer, "isOpened", lambda: False)():
            log.warning("OpenCV writer failed—switching to imageio-ffmpeg")
            self.writer = imageio.get_writer(
                self.filename.replace('.avi', '.mp4'),  # mp4 is fine
                fps=fps,
                codec='libx264',
                quality=8,          # you can tune this
                ffmpeg_log_level='warning'
            )

        self.is_recording = True
        log.info(f"Recording → {self.filename}")

    def write_frame(self, frame):
        """frame: BGR numpy array from camera"""
        if not self.is_recording:
            return

        # if it's an imageio writer (has append_data)
        if hasattr(self.writer, "append_data"):
            rgb = frame[..., ::-1]
            self.writer.append_data(rgb)
        else:
            self.writer.write(frame)

        self.frame_count += 1

    def stop(self):
        if not self.is_recording:
            return
        # close whichever writer you’ve got
        try:
            self.writer.close()
        except AttributeError:
            # cv2 writer has release()
            self.writer.release()
        log.info(f"Stopped recording: {self.filename}  total_frames={self.frame_count}")
        self.is_recording = False

class CSVRecorder:
    def __init__(self, filename):
        # make sure the folder exists
        os.makedirs(os.path.dirname(filename) or '.', exist_ok=True)
        self.filename = filename
        # open CSV and write a header row
        self.file = open(self.filename, 'w', newline='')
        self.writer = csv.writer(self.file)
        self.writer.writerow(['time', 'frame_index', 'value'])
        self.is_recording = True
        log.info(f"CSVRecorder started for {self.filename}")

    def write_data(self, t, frame_idx, p):
        if self.is_recording:
            self.writer.writerow([t, frame_idx, p])

    def stop(self):
        if not self.is_recording:
            return
        self.file.close()
        self.is_recording = False
        log.info(f"Stopped CSV recording for {self.filename}")


class TrialRecorder:
    def __init__(self, basepath, fps, frame_size,
                 video_codec=DEFAULT_VIDEO_CODEC,
                 video_ext=DEFAULT_VIDEO_EXTENSION):
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.basepath_with_ts = f"{basepath}_{ts}"

        # Decide on filename & recorder class based on extension
        if video_ext.lower() in ('tif','tiff'):
            # full-res TIFF stack
            tif_filename = f"{self.basepath_with_ts}.tif"
            self.video = TiffStackRecorder(tif_filename, frame_shape=frame_size)
            # Native FFmpeg capture from DirectShow device
            # video_codec is being repurposed to carry the device name
            self.video = FFmpegRecorder(
                device_name=video_codec,
                out_path=self.basepath_with_ts,
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
