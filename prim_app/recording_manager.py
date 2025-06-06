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

    This version buffers any camera frames until the first Arduino (pressure) tick arrives.
    Once the first pressure sample comes in, it opens both CSV and TIFF and dumps all
    buffered frames, ensuring that CSV rows and TIFF pages stay aligned.
    """

    # Emitted when the recording truly finishes closing files.
    finished = pyqtSignal()

    def __init__(self, output_dir, parent=None):
        super().__init__(parent)
        self.output_dir = output_dir

        # Paths (set in start_recording, but files actually opened on first pressure)
        self._csv_path = None
        self._tiff_path = None

        # File handles and writers (only created once first pressure arrives)
        self.csv_file = None
        self.csv_writer = None
        self.tif_writer = None

        # Flags & buffers
        self.is_recording = False
        self._got_first_sample = False
        self._pending_frames = (
            []
        )  # Will hold QImage instances until first pressure tick
        self._frame_counter = 0

    @pyqtSlot()
    def start_recording(self):
        """
        Called when the QThread hosting this object starts.
        Prepares paths but does not open files until the first pressure tick.
        """
        timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        base_name = f"recording_{timestamp}"

        os.makedirs(self.output_dir, exist_ok=True)
        self._csv_path = os.path.join(self.output_dir, f"{base_name}_pressure.csv")
        self._tiff_path = os.path.join(self.output_dir, f"{base_name}_video.tif")

        # Reset flags and buffers
        self.is_recording = True
        self._got_first_sample = False
        self._pending_frames.clear()
        self._frame_counter = 0

        print(
            f"[RecordingManager] Ready to record →\n  CSV will be: {self._csv_path}\n  TIFF will be: {self._tiff_path}"
        )
        print(f"[RecordingManager] Waiting for first pressure sample to open files...")

    @pyqtSlot(int, float, float)
    def append_pressure(self, frameIdx, t_device, pressure):
        """
        Slot connected to SerialThread.data_ready(frameIdx, t_device, pressure).
        On the first call, opens CSV and TIFF, dumps any buffered frames,
        then writes the first pressure row. Subsequent calls simply append.
        """
        if not self.is_recording:
            return

        # If this is the first pressure sample, open files & drain buffer
        if not self._got_first_sample:
            self._got_first_sample = True

            # 1) Open CSV and write header
            try:
                self.csv_file = open(self._csv_path, "w", newline="")
                self.csv_writer = csv.writer(self.csv_file)
                self.csv_writer.writerow(["frameIdx", "deviceTime", "pressure"])
            except Exception as e:
                print(f"[RecordingManager] Failed to open CSV for writing: {e}")
                self.is_recording = False
                return

            # 2) Open the multipage TIFF writer
            try:
                self.tif_writer = tifffile.TiffWriter(self._tiff_path, bigtiff=True)
            except Exception as e:
                print(f"[RecordingManager] Failed to open TIFF for writing: {e}")
                if self.csv_file:
                    self.csv_file.close()
                    self.csv_file = None
                    self.csv_writer = None
                self.is_recording = False
                return

            print(
                f"[RecordingManager] Recording truly started →\n  CSV: {self._csv_path}\n  TIFF: {self._tiff_path}"
            )

            # 3) Dump any buffered frames that arrived before the first pressure sample
            for buffered_qimage in self._pending_frames:
                try:
                    arr = self._qimage_to_numpy(buffered_qimage)
                    metadata = {"frameIdx": self._frame_counter}
                    self.tif_writer.write(arr, description=json.dumps(metadata))
                    self._frame_counter += 1
                except Exception as e:
                    print(
                        f"[RecordingManager] Error writing buffered frame {self._frame_counter}: {e}"
                    )
            self._pending_frames.clear()

        # Now, write the current pressure sample
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
        Buffers frames until first pressure arrives; after that, writes directly.
        """
        if not self.is_recording:
            return

        # If first pressure hasn't arrived yet, buffer this frame
        if not self._got_first_sample:
            # Store the QImage itself; we'll convert and flush once we open TIFF
            self._pending_frames.append(qimage)
            return

        # Once we've seen the first pressure, the TIFF writer should be open
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
        Slot to be called from the main/UI thread when the user clicks "Stop Recording".
        Closes TIFF and CSV (if open), clears state, and emits 'finished'.
        """
        if not self.is_recording:
            return

        self.is_recording = False

        # Close TIFF writer (if it was opened)
        try:
            if self.tif_writer:
                self.tif_writer.close()
                self.tif_writer = None
        except Exception as e:
            print(f"[RecordingManager] Error closing TIFF: {e}")

        # Close CSV file (if it was opened)
        try:
            if self.csv_file:
                self.csv_file.close()
                self.csv_file = None
                self.csv_writer = None
        except Exception as e:
            print(f"[RecordingManager] Error closing CSV: {e}")

        # Clear any buffers and reset state
        self._pending_frames.clear()
        self._got_first_sample = False
        self._frame_counter = 0

        print("[RecordingManager] Recording stopped and files closed.")
        self.finished.emit()

    def _qimage_to_numpy(self, qimage):
        """
        Convert a PyQt5 QImage → H×W×3 numpy.ndarray (uint8, RGB).
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
