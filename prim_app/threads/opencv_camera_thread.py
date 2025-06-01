# prim_app/threads/opencv_camera_thread.py

import cv2
import time
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
import logging

log = logging.getLogger(__name__)


class OpenCVCameraThread(QThread):
    frame_ready = pyqtSignal(np.ndarray)
    camera_properties_updated = pyqtSignal(dict)
    camera_info_reported = pyqtSignal(dict)

    def __init__(self, index=0, resolution=(640, 480), fps=30, parent=None):
        super().__init__(parent)
        self.camera_index = index
        self.target_width, self.target_height = resolution
        self.target_fps = fps
        self._running = True
        self.cap = None

    def run(self):
        log.info(f"Attempting to open OpenCV camera at index {self.camera_index}...")
        self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            log.error("Failed to open camera.")
            return

        # --- Set initial resolution and frame rate ---
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.target_width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.target_height)
        self.cap.set(cv2.CAP_PROP_FPS, self.target_fps)

        # Set to auto exposure mode
        self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
        self.cap.set(cv2.CAP_PROP_EXPOSURE, -1)

        # Allow adjustment
        time.sleep(1)

        actual_w = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        actual_h = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        log.info(f"Camera opened. Resolution: {actual_w}x{actual_h}")

        # Emit properties
        props = {
            "Gain": self.cap.get(cv2.CAP_PROP_GAIN),
            "AutoExposure": self.cap.get(cv2.CAP_PROP_AUTO_EXPOSURE),
            "Exposure": self.cap.get(cv2.CAP_PROP_EXPOSURE),
            "Width": actual_w,
            "Height": actual_h,
            "FPS": self.cap.get(cv2.CAP_PROP_FPS),
        }
        log.debug(f"Camera properties: {props}")
        self.camera_properties_updated.emit(props)
        self.camera_info_reported.emit(props)

        while self._running:
            ret, frame = self.cap.read()
            if ret and frame is not None:
                self.frame_ready.emit(frame)
            time.sleep(1 / self.target_fps)

        self.cap.release()
        log.info("OpenCV camera released.")

    def stop(self):
        self._running = False
        self.wait()

    def set_auto_exposure(self, enabled: bool):
        if self.cap:
            self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75 if enabled else 0.25)

    def set_gain(self, value: float):
        if self.cap:
            self.cap.set(cv2.CAP_PROP_GAIN, value)

    def set_camera_property(self, name: str, value: float):
        if not self.cap:
            return
        if name == "AutoExposure":
            self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75 if value else 0.25)
            actual = self.cap.get(cv2.CAP_PROP_AUTO_EXPOSURE)
            log.debug(f"[Cam] AutoExposure set → requested={value}, actual={actual}")
        elif name == "Gain":
            self.cap.set(cv2.CAP_PROP_GAIN, value)
            actual = self.cap.get(cv2.CAP_PROP_GAIN)
            log.debug(f"[Cam] Gain set → requested={value}, actual={actual}")
        else:
            log.warning(f"Unknown camera property '{name}' requested to set.")
