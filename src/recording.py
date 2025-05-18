import os, time, csv, threading, logging
from pycromanager import Bridge

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
    Uses pycromanager to grab frames and writes an AVI or multi-page TIFF.
    """

    def __init__(self, out_path, fps, frame_size, video_ext="avi", video_codec="XVID"):
        # start µManager
        self.bridge = Bridge()
        self.mmcore = self.bridge.get_core()

        # build output path & writer based on extension
        ext = video_ext.lower()
        dirname = os.path.dirname(out_path) or "."
        os.makedirs(dirname, exist_ok=True)

        self.fps = fps
        self.frame_size = frame_size  # (w, h)
        self.ext = ext
        self.video_codec = video_codec
        self.out_path = f"{out_path}.{ext}"
        self.frame_count = 0
        self._stop_event = threading.Event()
        self.thread = None
        self.is_recording = False

    def start(self):
        # launch acquisition thread
        self.is_recording = True
        self.thread = threading.Thread(target=self._acquire_loop, daemon=True)
        self.thread.start()

    def _acquire_loop(self):
        # begin continuous grab
        self.mmcore.startContinuousSequenceAcquisition(0)

        if self.ext == "avi":
            import cv2

            fourcc = cv2.VideoWriter_fourcc(*self.video_codec)
            writer = cv2.VideoWriter(self.out_path, fourcc, self.fps, self.frame_size)
        else:  # tiff stack
            import tifffile

            writer = None  # we'll call tifffile.imwrite below

        try:
            while not self._stop_event.is_set():
                tagged = self.bridge.get_tagged_image()
                img = tagged.pix.reshape(self.frame_size[1], self.frame_size[0])

                if self.ext == "avi":
                    # convert mono→BGR if needed
                    frame = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
                    writer.write(frame)
                else:
                    # multi-page TIFF append
                    tifffile.imwrite(self.out_path, img, append=True)

                self.frame_count += 1

        finally:
            if self.ext == "avi":
                writer.release()
            self.mmcore.stopSequenceAcquisition()

    def stop(self):
        if not self.is_recording:
            return
        self._stop_event.set()
        self.thread.join()
        self.is_recording = False
        log.info(
            f"Stopped µManager recorder → {self.out_path} ({self.frame_count} frames)"
        )


class TrialRecorder:
    """
    Always uses MMRecorder + CSVRecorder in lock-step.
    """

    def __init__(self, basepath, fps, frame_size, video_ext="avi", video_codec="XVID"):
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.base = f"{basepath}_{ts}"

        # video + CSV
        self.video = MMRecorder(
            self.base, fps, frame_size, video_ext=video_ext, video_codec=video_codec
        )
        self.video.start()
        log.info("Started µManager video recorder")

        self.csv = CSVRecorder(self.base + ".csv")

    def write_video_frame(self, frame):
        # no-op: MMRecorder streams autonomously
        pass

    def write_csv_data(self, t, frame_idx, pressure):
        self.csv.write_data(t, frame_idx, pressure)

    def stop(self):
        self.video.stop()
        self.csv.stop()

    @property
    def is_recording(self):
        return self.video.is_recording

    @property
    def video_frame_count(self):
        return self.video.frame_count
