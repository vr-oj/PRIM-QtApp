#!/usr/bin/env python3
import sys
import imagingcontrol4 as ic4
from PySide6.QtWidgets import QApplication
from imagingcontrol4.pyside6.display import DisplayWindow


def main():
    # 1) Initialize the IC4 library
    ic4.Library.init()  # :contentReference[oaicite:0]{index=0}

    # 2) Enumerate devices
    devices = ic4.DeviceEnum.devices()
    if not devices:
        print("No IC4-compatible cameras found.")
        ic4.Library.exit()
        return
    dev = devices[0]
    print(
        f"Opening camera: {dev.model_name} (S/N: {dev.serial})"
    )  # :contentReference[oaicite:1]{index=1}

    # 3) Open the camera
    grabber = ic4.Grabber()
    grabber.device_open(dev)

    # 4) Set up Qt application and OpenGL viewfinder
    app = QApplication(sys.argv)
    view = DisplayWindow()
    view.setWindowTitle("IC4 Live OpenGL Viewfinder")
    view.show()

    # 5) Hook the grabber’s stream to the OpenGL display and start acquisition
    disp = view.as_display()
    grabber.stream_setup(display=disp)  # :contentReference[oaicite:2]{index=2}

    # 6) Enter the Qt event loop
    exit_code = app.exec()

    # 7) Clean up
    if grabber.is_streaming:
        grabber.stream_stop()
    if grabber.is_device_open:
        grabber.device_close()
    ic4.Library.exit()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
