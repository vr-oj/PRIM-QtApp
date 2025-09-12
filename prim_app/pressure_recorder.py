import csv
import os
import time
import logging
from typing import Optional

log = logging.getLogger(__name__)


class PressureCsvRecorder:
    """Minimal CSV writer for pressure samples.

    Usage:
      rec = PressureCsvRecorder()
      rec.start(path)
      rec.append(frame_idx, t_device, pressure)
      rec.stop()
    """

    def __init__(self) -> None:
        self._path: Optional[str] = None
        self._csv = None
        self._writer = None
        self._samples = 0

    @property
    def path(self) -> Optional[str]:
        return self._path

    @property
    def is_active(self) -> bool:
        return self._writer is not None

    def start(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        f = open(path, "w", newline="")
        self._csv = f
        self._writer = csv.writer(f)
        self._writer.writerow(["frameIdx", "deviceTime", "pressure"])
        self._path = path
        self._samples = 0
        log.info(f"Started CSV recording: {path}")

    def append(self, frame_idx: int, t_device: float, pressure: float) -> None:
        if not self._writer:
            return
        try:
            self._writer.writerow([frame_idx, t_device, pressure])
            self._samples += 1
        except Exception:
            log.exception("Error writing CSV row")

    def stop(self) -> Optional[str]:
        path = self._path
        try:
            if self._csv:
                self._csv.close()
        finally:
            self._csv = None
            self._writer = None
            self._path = None
        log.info(f"Stopped CSV recording. Wrote {self._samples} samples to: {path}")
        return path

