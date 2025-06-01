# ic4_test.py
import imagingcontrol4 as ic4

print("✅ Starting IC4 test...")

# Step 1: Initialize the library
ic4.Library.init()
print("✅ IC4 Library initialized")

# Step 2: Create a Grabber instance
grabber = ic4.Grabber()
print("✅ Grabber created")

# Step 3: List available devices
devices = ic4.devenum.get_device_list()
if not devices:
    print("❌ No devices found.")
    exit(1)

# Pick the first DMK camera
camera = next((dev for dev in devices if "DMK" in dev.name), None)
if not camera:
    print("❌ No DMK camera found.")
    exit(1)

print(f"✅ Found camera: {camera.name}")

# Step 4: Open the camera
grabber.open_device(camera)
print("✅ Camera opened successfully")

# Step 5: List all properties
props = grabber.get_property_map()
print("✅ Retrieved property map")


# Try reading key properties
def read_prop(name):
    try:
        prop = props.get_property(name)
        value = prop.get_value()
        print(f"🔍 {name}: {value}")
    except Exception as e:
        print(f"⚠️  Could not read {name}: {e}")


for pname in ["Exposure Auto", "Exposure", "Gain", "Frame Rate"]:
    read_prop(pname)

# Done
grabber.close_device()
print("✅ Camera closed")
