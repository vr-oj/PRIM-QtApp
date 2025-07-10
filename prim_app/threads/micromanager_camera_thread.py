import logging
import os
import socket
import sys

import numpy as np
from pymmcore_plus import CMMCorePlus
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

try:
    # pymmcore-plus >=0.4 provides Launcher in pymmcore_plus.launcher
    from pymmcore_plus.launcher import Launcher
except Exception:  # pragma: no cover - fallback for older mmpycorex package
    try:
        from mmpycorex.launcher import Launcher  # type: ignore
    except Exception:  # package not available
        Launcher = None  # type: ignore


def find_free_port(start=4827, end=4900):
    """Return a free localhost TCP port in the given range."""
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port in {start}-{end}")


log = logging.getLogger(__name__)


class MicroManagerCameraThread(QThread):
    """Acquire frames from µManager using a headless ``Launcher`` if available."""

    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str)

    def __init__(
        self,
        parent=None,
        mm_path=None,
        config_file=None,
        adapter_paths=None,
        zmq_port=None,
    ):
        super().__init__(parent)
        self._stop_requested = False
        self.core = None
        self.launcher = None
        self.mm_path = mm_path
        self.config_file = config_file
        self.adapter_paths = adapter_paths or []
        try:
            self.zmq_port = zmq_port if zmq_port is not None else find_free_port()
        except RuntimeError as e:
            self.zmq_port = None
            self.error.emit(str(e))

    def run(self):
        try:
            if self.zmq_port is None:
                return

            if not self.config_file:
                raise RuntimeError("No config file provided for µManager.")

            if self.mm_path is None:
                if getattr(sys, "frozen", False):
                    base = os.path.dirname(sys.executable)
                else:
                    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                self.mm_path = os.path.join(base, "micromanager")

            os.environ["MICROMANAGER_PATH"] = self.mm_path

            try:
                if Launcher is None:
                    raise RuntimeError("Launcher class not available")
                self.launcher = Launcher(
                    port=self.zmq_port, adapter_paths=self.adapter_paths
                )
                self.core = self.launcher.get_core()
                self.core.setUseTimeouts(True)
                self.core.enableStderrLog(False)
            except Exception as e:
                self.error.emit(
                    f"Failed to start µManager headless on port {self.zmq_port}: {e}"
                )
                # fallback to headful load
                try:
                    self.core = CMMCorePlus(adapter_paths=self.adapter_paths)
                    self.core.loadSystemConfiguration(self.config_file)
                except Exception as e2:
                    self.error.emit(f"Fallback headful µManager load failed: {e2}")
                    return

            try:
                cam = self.core.getLoadedDevices()[0]
                self.core.setCameraDevice(cam)
                self.core.initializeDevice(cam)
                self.core.startContinuousSequenceAcquisition(0)
            except Exception as e:
                self.error.emit(f"µManager acquisition setup failed: {e}")
                return

            while not self._stop_requested:
                try:
                    tagged = self.core.popNextTaggedImage()
                    arr = tagged.as_array()
                    h, w = arr.shape[:2]
                    if arr.ndim == 2:
                        qimg = QImage(
                            arr.data, w, h, arr.strides[0], QImage.Format_Grayscale8
                        ).copy()
                    else:
                        qimg = QImage(
                            arr.data, w, h, arr.strides[0], QImage.Format_RGB888
                        ).copy()
                    self.frame_ready.emit(qimg, arr)
                except Exception:
                    self.msleep(5)

            try:
                self.core.stopSequenceAcquisition()
                self.core.reset()
            except Exception:
                pass

        except Exception as e:
            log.error(f"MicroManagerCameraThread error: {e}")
            self.error.emit(str(e))
        finally:
            self.core = None

    def stop(self):
        self._stop_requested = True
