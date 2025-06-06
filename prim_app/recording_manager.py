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
      - append_frame(frameIdx: int, qimage: QImage)
    and writes those to a CSV and a multipage TIFF respectively. When stop_recording()
    is called, it flushes and closes both files and emits 'finished'.
    """

    # Emitted when the recording truly finishes closing files.
    finished = pyqtSignal()

    def __init__(self, output_dir, parent=None):
        super().__init__(parent)
        self.output_dir = output_dir

        # File handles and writers will be created in start_recording()
        self.csv_file = None
        self.csv_writer = None
        self.tif_writer = None

        # Once True, slots will actually write; once False, they do nothing.
        self.is_recording = False

        # Keep track of how many frames we have written:
        self._frame_counter = 0

    @pyqtSlot()
    def start_recording(self):
        """
        Called when the QThread hosting this object starts. Opens a new CSV and TIFF
        in `self.output_dir` with a timestamped basename.
        """
        timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        base_name = f"recording_{timestamp}"

        os.makedirs(self.output_dir, exist_ok=True)
        csv_path = os.path.join(self.output_dir, f"{base_name}_pressure.csv")
        tiff_path = os.path.join(self.output_dir, f"{base_name}_video.tif")

        # 1) Open the CSV file and write header
        try:
            self.csv_file = open(csv_path, "w", newline="")
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow(["frameIdx", "deviceTime", "pressure"])
        except Exception as e:
            print(f"[RecordingManager] Failed to open CSV for writing: {e}")
            # If the CSV fails to open, we will not record.
            self.is_recording = False
            return

        # 2) Open the multipage TIFF writer
        try:
            # bigtiff=True allows large files >4 GB
            self.tif_writer = tifffile.TiffWriter(tiff_path, bigtiff=True)
        except Exception as e:
            print(f"[RecordingManager] Failed to open TIFF for writing: {e}")
            # Close CSV if TIFF fails
            if self.csv_file:
                self.csv_file.close()
                self.csv_file = None
                self.csv_writer = None
            self.is_recording = False
            return

        self.is_recording = True
        print(
            f"[RecordingManager] Recording started →\n  CSV: {csv_path}\n  TIFF: {tiff_path}"
        )

    @pyqtSlot(int, float, float)
    def append_pressure(self, frameIdx, t_device, pressure):
        """
        Slot connected to SerialThread.data_ready(frameIdx, t_device, pressure).
        Writes a new CSV row if recording is active.
        """
        if not self.is_recording or self.csv_writer is None:
            return

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
        Converts QImage → numpy array, then writes a new page to the TIFF. Each
        page is tagged with a sequential frame index starting at zero.
        """
        if not self.is_recording or self.tif_writer is None:
            return

        try:
            # Convert QImage → H×W×3 numpy array
            arr = self._qimage_to_numpy(qimage)
            # Use the internal frame counter as our "frameIdx" metadata
            metadata = {"frameIdx": self._frame_counter}
            # Write one page to the multipage TIFF
            self.tif_writer.write(arr, description=json.dumps(metadata))
            self._frame_counter += 1
        except Exception as e:
            # Reference the same counter in the error message (minus one, since
            # we only increment after a successful write)
            failed_idx = max(0, self._frame_counter)
            print(
                f"[RecordingManager] Error writing TIFF page for frame {failed_idx}: {e}"
            )

    @pyqtSlot()
    def stop_recording(self):
        """
        Slot to be called from the main/UI thread when the user clicks "Stop Recording".
        This will flush any remaining buffered data, close both CSV and TIFF, then
        emit 'finished' so the QThread can quit.
        """
        if not self.is_recording:
            return

        self.is_recording = False

        # 1) Close TIFF writer
        try:
            if self.tif_writer:
                self.tif_writer.close()
                self.tif_writer = None
        except Exception as e:
            print(f"[RecordingManager] Error closing TIFF: {e}")

        # 2) Close CSV file
        try:
            if self.csv_file:
                self.csv_file.close()
                self.csv_file = None
                self.csv_writer = None
        except Exception as e:
            print(f"[RecordingManager] Error closing CSV: {e}")

        print("[RecordingManager] Recording stopped and files closed.")
        self.finished.emit()

    def _qimage_to_numpy(self, qimage):
        """
        Convert a PyQt5 QImage (any format) → a H×W×3 numpy.ndarray (uint8, RGB).
        If the QImage has an alpha channel, we discard it.
        """
        # Ensure it’s in a known format (ARGB32) so bits() is contiguous.
        qimg = qimage.convertToFormat(qimage.Format_ARGB32)

        w = qimg.width()
        h = qimg.height()
        ptr = qimg.bits()
        ptr.setsize(qimg.byteCount())
        arr = np.frombuffer(ptr, np.uint8).reshape((h, w, 4))
        # Drop alpha channel → BGR order because QImage stores it that way
        # We want RGB order. Swap channels 0 and 2.
        arr_rgb = arr[:, :, [2, 1, 0]]
        return arr_rgb
