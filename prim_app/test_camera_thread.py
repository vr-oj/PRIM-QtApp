# File: test_camera_thread.py

import sys
import time
from PyQt5.QtWidgets import QApplication
from threads.sdk_camera_thread import SDKCameraThread


def on_grabber_ready():
    print("→ Grabber is ready. Camera streaming should start imminently.")


def on_frame_ready(qimg, buf):
    # Just print size and dtype of the underlying numpy buffer
    print(f"→ Frame received: {qimg.width()}×{qimg.height()}, Format=Grayscale8")


def on_error(msg, code):
    print(f"→ ERROR from camera thread: {msg} (code={code})")
    # Immediately stop thread if error occurs
    cam_thread.stop()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    cam_thread = SDKCameraThread(desired_fps=5)  # 5 FPS for testing
    cam_thread.grabber_ready.connect(on_grabber_ready)
    cam_thread.frame_ready.connect(on_frame_ready)
    cam_thread.error.connect(on_error)

    print("Starting camera thread...")
    cam_thread.start()

    # Let it run for 5 seconds
    time.sleep(5)

    print("Stopping camera thread...")
    cam_thread.stop()
    cam_thread.wait()

    print("Test complete. Exiting.")
    sys.exit(0)
