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
    """Manage synchronized writing of pressure data and camera frames."""

    # Emitted when :func:`start_recording` has finished its setup and the worker
    # is ready to receive the first Arduino tick.  The main window can listen for
    # this signal to safely start the hardware acquisition.
    ready_for_acquisition = pyqtSignal()
    finished = pyqtSignal()

    def __init__(self, output_dir, parent=None):
        super().__init__(parent)
        self.output_dir = output_dir

        # Paths (populated in ``start_recording``)
        self._csv_path = None
        self._tiff_path = None

        # File handles & writers
        self.csv_file = None
        self.csv_writer = None
        self.tif_writer = None

        # Recording flags
        self.is_recording = False
        self._got_first_sample = False

        # Frame counter
        self._frame_counter = 0

    @pyqtSlot()
    def start_recording(self):
        """Prepare file paths and wait for the first pressure sample."""
        timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        base_name = f"recording_{timestamp}"

        os.makedirs(self.output_dir, exist_ok=True)
        self._csv_path = os.path.join(self.output_dir, f"{base_name}_pressure.csv")
        self._tiff_path = os.path.join(self.output_dir, f"{base_name}_video.tif")

        self.is_recording = True
        self._got_first_sample = False
        self._frame_counter = 0

        print(
            f"[RecordingManager] Ready to record →\n  CSV will be: {self._csv_path}\n  TIFF will be: {self._tiff_path}"
        )
        print("[RecordingManager] Waiting for the first Arduino tick to open files...")
        # Notify the GUI that the worker thread finished setup and the files
        # paths have been prepared.  The application can now start the Arduino
        # so the first sample will create the CSV/TIFF files.
        self.ready_for_acquisition.emit()

    @pyqtSlot(int, float, float)
    def append_pressure(self, frameIdx, t_device, pressure):
        """Handle a pressure sample from the serial thread."""
        if not self.is_recording:
            return

        if not self._got_first_sample:
            self._got_first_sample = True
            try:
                self.csv_file = open(self._csv_path, "w", newline="")
                self.csv_writer = csv.writer(self.csv_file)
                self.csv_writer.writerow(["frameIdx", "deviceTime", "pressure"])
            except Exception as e:
                print(f"[RecordingManager] Failed to open CSV: {e}")
                self.is_recording = False
                return
            try:
                self.tif_writer = tifffile.TiffWriter(self._tiff_path, bigtiff=True)
            except Exception as e:
                print(f"[RecordingManager] Failed to open TIFF: {e}")
                if self.csv_file:
                    self.csv_file.close()
                    self.csv_file = None
                    self.csv_writer = None
                self.is_recording = False
                return
            print(
                f"[RecordingManager] Recording truly started →\n  CSV: {self._csv_path}\n  TIFF: {self._tiff_path}"
            )

        if self.csv_writer:
            try:
                self.csv_writer.writerow([frameIdx, t_device, pressure])
            except Exception as e:
                print(
                    f"[RecordingManager] Error writing CSV row ({frameIdx}, {t_device}, {pressure}): {e}"
                )

    @pyqtSlot(QImage, object)
    def append_frame(self, qimage, raw):
        """Handle a camera frame from the camera thread."""
        if not self.is_recording or not self._got_first_sample:
            return

        if self.tif_writer:
            try:
                arr = self._qimage_to_numpy(qimage)
                metadata = {"frameIdx": self._frame_counter}
                self.tif_writer.write(arr, description=json.dumps(metadata))
                self._frame_counter += 1
            except Exception as e:
                failed_idx = max(0, self._frame_counter)
                print(f"[RecordingManager] Error writing TIFF page for frame {failed_idx}: {e}")

    @pyqtSlot()
    def stop_recording(self):
        """Close files and reset state."""
        if not self.is_recording:
            return

        self.is_recording = False

        try:
            if self.tif_writer:
                self.tif_writer.close()
                self.tif_writer = None
        except Exception as e:
            print(f"[RecordingManager] Error closing TIFF: {e}")

        try:
            if self.csv_file:
                self.csv_file.close()
                self.csv_file = None
                self.csv_writer = None
        except Exception as e:
            print(f"[RecordingManager] Error closing CSV: {e}")

        self._got_first_sample = False
        self._frame_counter = 0

        print("[RecordingManager] Recording stopped and files closed.")
        self.finished.emit()

    def _qimage_to_numpy(self, qimage):
        """Convert a ``QImage`` to a ``numpy.ndarray``.

        If the image is already 8‑bit grayscale, the raw bytes are read
        directly into a ``(H, W)`` ``uint8`` array.  Otherwise the image is
        converted to ARGB32 and the returned array has shape ``(H, W, 3)`` in
        RGB order.
        """

        fmt = qimage.format()
        if fmt in (QImage.Format_Grayscale8, QImage.Format_Indexed8):
            w, h = qimage.width(), qimage.height()
            ptr = qimage.bits()
            ptr.setsize(qimage.byteCount())
            arr = np.frombuffer(ptr, np.uint8).reshape((h, w))
            return arr

        qimg = qimage.convertToFormat(QImage.Format_ARGB32)
        w, h = qimg.width(), qimg.height()
        ptr = qimg.bits()
        ptr.setsize(qimg.byteCount())
        arr = np.frombuffer(ptr, np.uint8).reshape((h, w, 4))
        return arr[:, :, [2, 1, 0]]
