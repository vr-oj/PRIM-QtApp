# File: test_camera_thread.py

import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
from threads.sdk_camera_thread import SDKCameraThread


def on_grabber_ready():
    print("→ Grabber is ready. Camera is open with default settings.")


def on_error(msg, code):
    print(f"→ ERROR from camera thread: {msg} (code={code})")
    cam_thread.stop()
    # We can also schedule app.quit() here if desired:
    QTimer.singleShot(0, app.quit)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # 1) Instantiate the thread
    cam_thread = SDKCameraThread()
    cam_thread.grabber_ready.connect(on_grabber_ready)
    cam_thread.error.connect(on_error)

    print("Starting camera thread…")
    cam_thread.start()

    # 2) Schedule a stop() + app.quit() after 5 seconds (5000 ms)
    def finish_test():
        print("Stopping camera thread…")
        cam_thread.stop()
        cam_thread.wait()
        print("Test complete. Exiting.")
        app.quit()

    QTimer.singleShot(5000, finish_test)

    # 3) Run Qt’s event loop so signals actually fire
    sys.exit(app.exec_())
