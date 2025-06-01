# ic4_test.py
import imagingcontrol4 as ic4

print("✅ Starting IC4 test...")

# Step 1: Initialize the library
ic4.Library.init()
print("✅ IC4 Library initialized")

# Step 2: Create a Grabber instance
grabber = ic4.Grabber()
print("✅ Grabber created")

# Step 3: List available devices (correct method for your installed version)
try:
    device_list = grabber.get_available_video_capture_devices()
    if not device_list:
        print("❌ No devices found.")
        exit(1)
    print("✅ Available devices:")
    for i, dev in enumerate(device_list):
        print(f"  {i+1}. {dev.get_display_name()}")
except Exception as e:
    print(f"❌ Error getting device list: {e}")
    exit(1)

# Step 4: Try to open the first DMK camera
dmk_device = next((dev for dev in device_list if "DMK" in dev.get_display_name()), None)

if dmk_device is None:
    print("❌ No DMK camera found.")
    exit(1)

try:
    grabber.open_video_capture_device(dmk_device)
    print(f"✅ Opened camera: {dmk_device.get_display_name()}")
except Exception as e:
    print(f"❌ Failed to open camera: {e}")
    exit(1)

# Step 5: Try to access property map
try:
    props = grabber.get_property_map()
    print("✅ Retrieved property map")
except Exception as e:
    print(f"❌ Failed to access properties: {e}")

# Cleanup
grabber.close_video_capture_device()
print("✅ Camera closed")
