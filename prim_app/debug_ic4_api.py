import imagingcontrol4 as ic4

try:
    ic4.library.Library.init()
    print("✅ IC4 Library initialized")

    grabber = ic4.grabber.Grabber()
    print("✅ Grabber created")

    devices = grabber.get_available_video_capture_devices()
    print(f"🔍 Found {len(devices)} device(s):")
    for device in devices:
        print(f"  - {device.name}")
except Exception as e:
    print("❌ Error:", e)
