# prim_app/recording_manager.py

import os
import time
import csv
import json
import numpy as np
import tifffile
from PyQt5.QtCore import QObject, pyqtSlot, pyqtSignal
from PyQt5.QtGui import QImage


class RecordingManager(QObject):
    """
    A QObject that lives in its own QThread. It listens for:
      - append_pressure(frameIdx: int, t_device: float, pressure: float)
      - append_frame(qimage: QImage, raw_data: object)
    and writes those to a CSV and a multipage TIFF respectively. When stop_recording()
    is called, it flushes and closes both files and emits 'finished'.

    This version DROPS every camera frame until the first Arduino tick arrives,
    then starts writing lock‐step: one CSV row per pressure tick, one TIFF page
    per frame after that. No “extra” frames at the beginning or end.
    """

    # Emitted when the recording truly finishes closing files.
    finished = pyqtSignal()

    def __init__(self, output_dir, parent=None):
        super().__init__(parent)
        self.output_dir = output_dir

        # Paths (we compute them in start_recording but only open on first pressure)
        self._csv_path = None
        self._tiff_path = None

        # File handles & writers (initialized on first tick)
        self.csv_file = None
        self.csv_writer = None
        self.tif_writer = None

        # Recording flags
        self.is_recording = False
        self._got_first_sample = False

        # Frame counter (resets to 0 when first tick arrives)
        self._frame_counter = 0

    @pyqtSlot()
    def start_recording(self):
        """
        Called when the QThread hosting this object starts.
        Pre‐computes file paths but does NOT open them yet. We wait until
        the first append_pressure() call to actually open CSV + TIFF.
        """
        timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        base_name = f"recording_{timestamp}"

        os.makedirs(self.output_dir, exist_ok=True)
        self._csv_path = os.path.join(self.output_dir, f"{base_name}_pressure.csv")
        self._tiff_path = os.path.join(self.output_dir, f"{base_name}_video.tif")

        # Reset flags & counters
        self.is_recording = True
        self._got_first_sample = False
        self._frame_counter = 0

        print(
            f"[RecordingManager] Ready to record →\n  CSV will be: {self._csv_path}\n  TIFF will be: {self._tiff_path}"
        )
        print("[RecordingManager] Waiting for the first Arduino tick to open files...")

    @pyqtSlot(int, float, float)
    def append_pressure(self, frameIdx, t_device, pressure):
        """
        Slot connected to SerialThread.data_ready(frameIdx, t_device, pressure).
        On the very first call, opens CSV + TIFF and sets _got_first_sample=True.
        Then writes each pressure row as it arrives.
        """
        if not self.is_recording:
            return

        # If this is the first pressure sample, open CSV and TIFF now
        if not self._got_first_sample:
            self._got_first_sample = True

            # 1) Open the CSV file and write header
            try:
                self.csv_file = open(self._csv_path, "w", newline="")
                self.csv_writer = csv.writer(self.csv_file)
                self.csv_writer.writerow(["frameIdx", "deviceTime", "pressure"])
            except Exception as e:
                print(f"[RecordingManager] Failed to open CSV: {e}")
                self.is_recording = False
                return

            # 2) Open the multipage TIFF writer (bigtiff=True for >4GB)
            try:
                self.tif_writer = tifffile.TiffWriter(self._tiff_path, bigtiff=True)
            except Exception as e:
                print(f"[RecordingManager] Failed to open TIFF: {e}")
                # Close CSV if TIFF fails
                if self.csv_file:
                    self.csv_file.close()
                    self.csv_file = None
                    self.csv_writer = None
                self.is_recording = False
                return

            print(
                f"[RecordingManager] Recording truly started →\n  CSV: {self._csv_path}\n  TIFF: {self._tiff_path}"
            )
            # From now on, append_frame() will write frames starting at counter=0.

        # Write this pressure row
        if self.csv_writer:
            try:
                self.csv_writer.writerow([frameIdx, t_device, pressure])
            except Exception as e:
                print(
                    f"[RecordingManager] Error writing CSV row ({frameIdx}, {t_device}, {pressure}): {e}"
                )

    @pyqtSlot(QImage, object)
    def append_frame(self, qimage, raw):
        """
        Slot connected to SDKCameraThread.frame_ready(QImage, raw_data).
        DROPS every frame until the first Arduino tick has arrived.
        After that, writes each frame into the TIFF with a sequential frameIdx.
        """
        if not self.is_recording or not self._got_first_sample:
            # We have not seen a pressure tick yet → drop this frame entirely.
            return

        # Once first tick has arrived, tif_writer must be open
        if self.tif_writer:
            try:
                arr = self._qimage_to_numpy(qimage)
                metadata = {"frameIdx": self._frame_counter}
                self.tif_writer.write(arr, description=json.dumps(metadata))
                self._frame_counter += 1
            except Exception as e:
                failed_idx = max(0, self._frame_counter)
                print(
                    f"[RecordingManager] Error writing TIFF page for frame {failed_idx}: {e}"
                )

    @pyqtSlot()
    def stop_recording(self):
        """
        Slot to be called from the main/UI thread when user clicks “Stop Recording”.
        Closes TIFF + CSV (if open), resets state, and emits finished.
        """
        if not self.is_recording:
            return

        self.is_recording = False

        # 1) Close TIFF writer (if it opened)
        try:
            if self.tif_writer:
                self.tif_writer.close()
                self.tif_writer = None
        except Exception as e:
            print(f"[RecordingManager] Error closing TIFF: {e}")

        # 2) Close CSV file (if it opened)
        try:
            if self.csv_file:
                self.csv_file.close()
                self.csv_file = None
                self.csv_writer = None
        except Exception as e:
            print(f"[RecordingManager] Error closing CSV: {e}")

        # Reset flags
        self._got_first_sample = False
        self._frame_counter = 0

        print("[RecordingManager] Recording stopped and files closed.")
        self.finished.emit()

    def _qimage_to_numpy(self, qimage):
        """
        Convert a PyQt5 QImage → H×W×3 numpy.ndarray (uint8, RGB).
        If there’s an alpha channel, drop it.
        """
        qimg = qimage.convertToFormat(qimage.Format_ARGB32)
        w, h = qimg.width(), qimg.height()
        ptr = qimg.bits()
        ptr.setsize(qimg.byteCount())
        arr = np.frombuffer(ptr, np.uint8).reshape((h, w, 4))
        arr_rgb = arr[:, :, [2, 1, 0]]  # Swap B<->R to get RGB
        return arr_rgb
