import cv2

from .base import CameraBase


class OpenCVCamera(CameraBase):
    """Simple OpenCV VideoCapture based camera backend."""

    def __init__(self, index=0):
        self.index = index
        self.cap = None

    def connect(self):
        self.cap = cv2.VideoCapture(self.index)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open camera index {self.index}")

    def disconnect(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def start_stream(self):
        # VideoCapture immediately provides frames once opened; nothing extra.
        pass

    def stop_stream(self):
        # Nothing to do for VideoCapture
        pass

    def get_frame(self):
        if self.cap is None:
            return None
        ret, frame = self.cap.read()
        if not ret:
            return None
        return frame

    def set_property(self, prop_name: str, value):
        if self.cap is None:
            return False
        prop_id = getattr(cv2, f"CAP_PROP_{prop_name.upper()}", None)
        if prop_id is None:
            return False
        return self.cap.set(prop_id, value)
