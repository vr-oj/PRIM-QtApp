# prim_app/threads/opencv_camera_thread.py

import logging
import cv2
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

log = logging.getLogger(__name__)


class OpenCVCameraThread(QThread):
    frame_ready = pyqtSignal(object)
    camera_error = pyqtSignal(str)
    camera_properties_updated = pyqtSignal(dict)
    camera_info_reported = pyqtSignal(dict)

    def __init__(self, device_index=0, resolution=(1280, 720), fps=10, parent=None):
        super().__init__(parent)
        self.device_index = device_index
        self.target_width, self.target_height = resolution
        self.target_fps = fps
        self.running = False
        self.cap = None

    def run(self):
        try:
            log.info(
                f"Attempting to open OpenCV camera at index {self.device_index}..."
            )
            self.cap = cv2.VideoCapture(self.device_index, cv2.CAP_DSHOW)

            if not self.cap.isOpened():
                self.camera_error.emit("OpenCV could not open camera.")
                return

            # Attempt to set resolution and FPS
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.target_width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.target_height)
            self.cap.set(cv2.CAP_PROP_FPS, self.target_fps)

            self.running = True
            log.info(
                f"Camera opened. Resolution: {self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)}x{self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)}"
            )

            # Emit properties on start
            self._emit_camera_properties()

            while self.running:
                ret, frame = self.cap.read()
                if ret:
                    self.frame_ready.emit(frame)
                else:
                    log.warning("Failed to read frame from camera.")
        except Exception as e:
            log.exception("Exception in OpenCVCameraThread")
            self.camera_error.emit(str(e))
        finally:
            if self.cap:
                self.cap.release()
                log.info("OpenCV camera released.")

    def stop(self):
        self.running = False

    def _emit_camera_properties(self):
        if not self.cap:
            return
        props = {
            "Gain": int(self.cap.get(cv2.CAP_PROP_GAIN)),
            "Brightness": int(self.cap.get(cv2.CAP_PROP_BRIGHTNESS)),
            "AutoExposure": self.cap.get(cv2.CAP_PROP_AUTO_EXPOSURE),
            "Exposure": self.cap.get(cv2.CAP_PROP_EXPOSURE),
            "Width": int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "Height": int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "FPS": self.cap.get(cv2.CAP_PROP_FPS),
        }
        self.camera_properties_updated.emit(props)
        log.debug(f"Camera properties: {props}")

    def set_camera_property(self, name, value):
        if not self.cap:
            return
        try:
            if name == "Gain":
                self.cap.set(cv2.CAP_PROP_GAIN, float(value))
            elif name == "Brightness":
                self.cap.set(cv2.CAP_PROP_BRIGHTNESS, float(value))
            elif name == "AutoExposure":
                # Use 0.25 for manual, 0.75 for auto (DirectShow)
                self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25 if not value else 0.75)
            elif name == "Exposure":
                self.cap.set(cv2.CAP_PROP_EXPOSURE, float(value))

            self._emit_camera_properties()
            log.info(f"Set {name} to {value}")
        except Exception as e:
            log.warning(f"Failed to set camera property {name}: {e}")
