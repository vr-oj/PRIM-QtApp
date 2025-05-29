import imagingcontrol4 as ic4

print("=== IC4 Force Reset Test ===")

try:
    ic4.Library.init()
    devices = ic4.DeviceEnum.devices()
    if not devices:
        print("❌ No devices found.")
    else:
        for i, dev in enumerate(devices):
            print(f"[{i}] {dev.model_name} - Serial: {dev.serial}")
        first = devices[0]
        print(f"Trying to open: {first.model_name} (Serial: {first.serial})")
        grabber = ic4.Grabber()
        device = grabber.device_open(first)

        if device is None:
            print("❌ grabber.device_open() returned None.")
        else:
            print("✅ Device opened successfully.")
            print("Attempting property_map reset...")
            try:
                device.reset_properties()
                print("✅ Properties reset.")
            except Exception as e:
                print(f"⚠️  Could not reset properties: {e}")
            grabber.device_close()
            print("✅ Device closed.")

except Exception as e:
    print(f"❌ Exception occurred: {e}")
finally:
    ic4.Library.exit()
    print("✅ Library exited.")
