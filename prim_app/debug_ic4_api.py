import imagingcontrol4 as ic4

print("Library version:", ic4.__version__)

try:
    ic4.library.Library.init()
    print("Library initialized.")

    grabber = ic4.grabber.Grabber()
    print("Grabber initialized.")

    devices = grabber.get_available_video_capture_devices()
    print("Available devices:")
    for dev in devices:
        print("  -", dev.name)
except Exception as e:
    print("Error:", e)
