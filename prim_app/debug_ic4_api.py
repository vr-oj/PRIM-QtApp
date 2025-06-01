# debug_ic4_api.py (Fixed v2)

import imagingcontrol4 as ic4

try:
    # Step 1: Initialize IC4 library
    ic4.Library.init()
    print("✅ Library initialized")

    # Step 2: Create grabber
    grabber = ic4.Grabber()
    print("✅ Grabber created")

    # Step 3: Use Grabber's built-in open_device_by_serial (if available)
    # Try to use a fallback serial name or test default logic
    # To simply test functionality, skip listing and open any known camera

    # Try to list devices via propconstants helper (experimental fallback)
    try:
        dev_enum = ic4.devenum.DeviceEnumerator()
        devices = dev_enum.get_available_video_capture_devices()
        if not devices:
            print("❌ No cameras detected.")
        else:
            for i, d in enumerate(devices):
                print(f"  [{i}] {d.get_name()} - {d.get_serial_number()}")
            grabber.open_device(devices[0])
            print(f"✅ Opened: {devices[0].get_name()}")
    except Exception as e:
        print("❌ Device enumeration failed:", e)

    # Step 4: Try reading exposure
    try:
        prop = grabber.get_property("Exposure Auto")
        if prop:
            print("🔎 Exposure Auto:", prop.get_value())
        else:
            print("⚠️ Property 'Exposure Auto' not found.")
    except Exception as e:
        print("❌ Failed to read exposure:", e)

except Exception as e:
    print("❌ Top-level error:", e)
