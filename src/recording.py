import cv2
import csv
import os
import time

class VideoRecorder:
    def __init__(self, filename, fourcc='mp4v', fps=30, frame_size=(640,480)):
        # Ensure output dir exists
        os.makedirs(os.path.dirname(filename) or '.', exist_ok=True)
        # OpenCV FourCC code
        fourcc_code = cv2.VideoWriter_fourcc(*fourcc)
        self.writer = cv2.VideoWriter(filename, fourcc_code, fps, frame_size)
        self.is_recording = True

    def write_frame(self, frame):
        if self.is_recording:
            # frame must be BGR numpy array
            self.writer.write(frame)

    def stop(self):
        self.is_recording = False
        self.writer.release()


class CSVRecorder:
    def __init__(self, filename, fieldnames=('time_s','pressure')):
        os.makedirs(os.path.dirname(filename) or '.', exist_ok=True)
        self.file = open(filename, 'w', newline='')
        self.writer = csv.DictWriter(self.file, fieldnames=fieldnames)
        self.writer.writeheader()
        self.is_recording = True

    def write(self, t, p):
        if self.is_recording:
            self.writer.writerow({'time_s': t, 'pressure': p})

    def stop(self):
        self.is_recording = False
        self.file.close()


class TrialRecorder:
    """Helper to coordinate video + CSV in a single object."""
    def __init__(self, basepath, fps, frame_size):
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        video_fn = f"{basepath}_{timestamp}.mp4"
        csv_fn   = f"{basepath}_{timestamp}.csv"
        self.video = VideoRecorder(video_fn, fps=fps, frame_size=frame_size)
        self.csv   = CSVRecorder(csv_fn)

    def write(self, frame, t, p):
        # frame: BGR image; t,p floats
        self.video.write_frame(frame)
        self.csv.write(t, p)

    def stop(self):
        self.video.stop()
        self.csv.stop()
