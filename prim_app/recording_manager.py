# prim_app/recording_manager.py

import os
import time
import csv
import json
import numpy as np
import tifffile
from PyQt5.QtCore import QObject, pyqtSlot, pyqtSignal
from PyQt5.QtGui import QImage
import logging

log = logging.getLogger(__name__)


class RecordingManager(QObject):
    """
    A QObject that lives in its own QThread. It listens for:
      - append_pressure(frameIdx: int, t_device: float, pressure: float)
      - append_frame(qimage: QImage, raw_data: object)
    and writes those to a CSV and a multipage TIFF respectively. When stop_recording()
    is called, it flushes and closes both files and emits 'finished'.

    Parameters
    ----------
    output_dir : str
        Destination directory for CSV and TIFF files.
    parent : QObject, optional
        Parent QObject.
    use_ome : bool, default True
        Write the TIFF as OME-TIFF with per-frame plane metadata.
    compression : str or None, default None
        TIFF compression algorithm. ``None`` writes uncompressed frames.

    This version DROPS every camera frame until the first Arduino tick arrives,
    then starts writing lock‐step: one CSV row per pressure tick, one TIFF page
    per frame after that. No “extra” frames at the beginning or end.
    """

    # Emitted when the recording truly finishes closing files.
    finished = pyqtSignal()

    def __init__(self, output_dir, parent=None, use_ome=True, compression=None):
        super().__init__(parent)
        self.output_dir = output_dir
        self.use_ome = use_ome
        self.compression = compression

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

        self._last_deviceTime = None
        self._last_pressure = None

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
        self._tiff_path = os.path.join(
            self.output_dir, f"{base_name}_video.ome.tif"
        )

        # Reset flags & counters
        self.is_recording = True
        self._got_first_sample = False
        self._frame_counter = 0

        log.info(
            "Ready to record →\n  CSV will be: %s\n  TIFF will be: %s",
            self._csv_path,
            self._tiff_path,
        )
        log.info("Waiting for the first Arduino tick to open files...")

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
                self.csv_writer.writerow(["frame_index", "device_time", "pressure"])
                # removed initial data write since it is duplicated by the code down below
            except Exception as e:
                log.error("Failed to open CSV: %s", e)
                self.is_recording = False
                return

            # 2) Open the multipage TIFF writer (bigtiff=True for >4GB)
            try:
                self.tif_writer = tifffile.TiffWriter(
                    self._tiff_path, bigtiff=True, ome=self.use_ome
                )
            except Exception as e:
                log.error("Failed to open TIFF: %s", e)
                # Close CSV if TIFF fails
                if self.csv_file:
                    self.csv_file.close()
                    self.csv_file = None
                    self.csv_writer = None
                self.is_recording = False
                return

            log.info(
                "Recording truly started →\n  CSV: %s\n  TIFF: %s",
                self._csv_path,
                self._tiff_path,
            )
            # From now on, append_frame() will write frames starting at counter=0.

        # Write this pressure row
        if self.csv_writer:
            try:
                self.csv_writer.writerow([frameIdx, t_device, pressure])
                # moved last variables from start_recording to here so that they get updated properly
                self._last_deviceTime = t_device
                self._last_pressure = pressure
            except Exception as e:
                log.error(
                    "Error writing CSV row (%s, %s, %s): %s",
                    frameIdx,
                    t_device,
                    pressure,
                    e,
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
                plane_meta = {
                    "TheT": self._frame_counter,
                    "DeltaT": self._last_deviceTime,
                    "Pressure": self._last_pressure,
                }
                ome_meta = {"axes": "TYX", "Plane": plane_meta}
                write_kwargs = {
                    "photometric": "minisblack",
                    "metadata": ome_meta,
                }
                if self.compression:
                    write_kwargs["compression"] = self.compression
                self.tif_writer.write(arr, **write_kwargs)
                self._frame_counter += 1
            except Exception as e:
                failed_idx = max(0, self._frame_counter)
                log.error(
                    "Error writing TIFF page for frame %s: %s",
                    failed_idx,
                    e,
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
            log.error("Error closing TIFF: %s", e)

        # 2) Close CSV file (if it opened)
        try:
            if self.csv_file:
                self.csv_file.close()
                self.csv_file = None
                self.csv_writer = None
        except Exception as e:
            log.error("Error closing CSV: %s", e)

        # Reset flags
        self._got_first_sample = False
        self._frame_counter = 0

        log.info("Recording stopped and files closed.")
        self.finished.emit()

    def _qimage_to_numpy(self, qimage):
        """
        Convert a ``QImage`` to a grayscale ``numpy.ndarray`` with shape ``(H, W)``.
        Any color channels are discarded.
        """
        qimg = qimage.convertToFormat(qimage.Format_Grayscale8)
        w, h = qimg.width(), qimg.height()
        ptr = qimg.bits()
        ptr.setsize(qimg.byteCount())
        arr = np.frombuffer(ptr, np.uint8).reshape((h, w))
        return arr
