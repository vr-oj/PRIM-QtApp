import cv2, csv, os, time

class VideoRecorder:
    def __init__(self, filename, fourcc='XVID', fps=30, frame_size=(640,480)):
        os.makedirs(os.path.dirname(filename) or '.', exist_ok=True)
        # e.g. filename ends in .avi, and we use XVID as the codec
        self.writer = cv2.VideoWriter(
            filename,
            cv2.VideoWriter_fourcc(*fourcc),
            fps,
            frame_size
        )
        self.frame_count = 0
        self.is_recording = True

    def write_frame(self, frame):
        if self.is_recording:
            self.writer.write(frame); self.frame_count+=1

    def stop(self):
        self.is_recording=False; self.writer.release()

class CSVRecorder:
    def __init__(self, filename, fieldnames=('time_s','pressure')):
        os.makedirs(os.path.dirname(filename) or '.', exist_ok=True)
        self.file = open(filename,'w',newline='')
        self.writer = csv.DictWriter(self.file, fieldnames=fieldnames)
        self.writer.writeheader(); self.is_recording=True

    def write(self, t, p):
        if self.is_recording:
            self.writer.writerow({'time_s':t,'pressure':p}); self.file.flush()

    def stop(self):
        self.is_recording=False; self.file.close()

class TrialRecorder:
    def __init__(self, basepath, fps, frame_size, ext='mp4'):
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.basepath = f"{basepath}_{ts}"
        self.video    = VideoRecorder(f"{self.basepath}.{ext}", ...)
        self.csv      = CSVRecorder(f"{self.basepath}.csv")

    def write(self, frame, t, p):
        self.video.write_frame(frame); self.csv.write(t, p)

    def stop(self):
        self.video.stop(); self.csv.stop()

    @property
    def video_frame_count(self):
        return self.video.frame_count
