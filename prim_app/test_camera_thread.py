# File: test_camera_thread.py

import sys
import time
from PyQt5.QtWidgets import QApplication
from prim_app.threads.sdk_camera_thread import SDKCameraThread


def on_grabber_ready():
    print("→ Grabber is ready. You can now query or set camera properties.")


def on_error(msg, code):
    print(f"→ ERROR from camera thread: {msg} (code={code})")
    cam_thread.stop()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Instantiate without desired_fps
    cam_thread = SDKCameraThread()
    cam_thread.grabber_ready.connect(on_grabber_ready)
    cam_thread.error.connect(on_error)

    print("Starting camera thread...")
    cam_thread.start()

    # Let it run for 5 seconds, then shut down
    time.sleep(5)
    print("Stopping camera thread...")
    cam_thread.stop()
    cam_thread.wait()
    print("Test complete. Exiting.")
    sys.exit(0)
