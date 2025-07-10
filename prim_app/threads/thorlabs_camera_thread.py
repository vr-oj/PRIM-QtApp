import threading
import numpy as np
from thorlabs_tsi_sdk.tl_camera import TLCameraSDK

class ThorlabsCameraThread(threading.Thread):
    def __init__(self, parent=None):
        super().__init__()
        self.parent = parent
        self.running = False
        self.sdk = TLCameraSDK()
        self.camera = None

    def run(self):
        self.running = True
        self.initialize_camera()
        while self.running:
            frame = self.get_frame()
            if frame is not None and self.parent is not None:
                self.parent.update_camera_frame(frame)
        self.shutdown()

    def initialize_camera(self):
        cameras = self.sdk.discover_available_cameras()
        if not cameras:
            print("No Thorlabs cameras found.")
            self.running = False
            return

        self.camera = self.sdk.open_camera(cameras[0])
        self.camera.exposure_time_us = 10000  # Example: 10 ms exposure
        self.camera.frames_per_trigger_zero_for_unlimited = 0
        self.camera.arm(2)  # Continuous mode
        self.camera.issue_software_trigger()

    def get_frame(self):
        if not self.camera:
            return None
        try:
            frame = self.camera.get_pending_frame_or_null()
            if frame:
                image = frame.image_buffer.copy()  # Already NumPy
                self.camera.dispose_frame(frame)
                # Convert to 8-bit if needed
                if image.dtype != np.uint8:
                    image = (image / image.max() * 255).astype(np.uint8)
                return image
        except Exception as e:
            print(f"Error getting frame: {e}")
        return None

    def stop(self):
        self.running = False

    def shutdown(self):
        if self.camera:
            self.camera.disarm()
            self.camera.dispose()
        self.sdk.dispose()
