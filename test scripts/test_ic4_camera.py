#!/usr/bin/env python3
"""
Simple test of IC4 camera live feed using the PySide6 DisplayWindow.
"""

import sys

import imagingcontrol4 as ic4
from imagingcontrol4.pyside6.display import DisplayWindow
from PySide6.QtWidgets import QApplication


def main():
    # 1) Initialize the IC4 library
    ic4.Library.init()  # Raises on failure :contentReference[oaicite:0]{index=0}

    # 2) Enumerate devices and pick the first one
    devices = ic4.DeviceEnum.devices()
    if not devices:
        print("No IC4-compatible cameras found.")
        return
    dev = devices[0]
    print(
        f"Opening camera: {dev.model_name} (S/N: {dev.serial})"
    )  # :contentReference[oaicite:1]{index=1}

    # 3) Open the camera
    grabber = ic4.Grabber()
    grabber.device_open(dev)

    # 4) Start Qt and display window
    app = QApplication(sys.argv)
    view = DisplayWindow()
    view.setWindowTitle("IC4 Live OpenGL Viewfinder")
    view.show()

    # 5) Connect the stream to the window’s OpenGL display
    disp = (
        view.as_display()
    )  # Returns an IC4 Display to pass to stream_setup :contentReference[oaicite:2]{index=2}
    grabber.stream_setup(display=disp)

    # 6) Run the Qt event loop
    app.exec()

    # 7) Clean up
    grabber.stream_stop()
    grabber.device_close()
    ic4.Library.exit()


if __name__ == "__main__":
    main()
