# debug_ic4_api.py

import imagingcontrol4 as ic4

try:
    # Step 1: Initialize the library
    ic4.Library.init()
    print("✅ Library initialized")

    # Step 2: Create the grabber
    grabber = ic4.Grabber()
    print("✅ Grabber created")

    # Step 3: List available devices
    device_list = ic4.DeviceEnum.enumerate()
    if not device_list:
        print("❌ No IC4-compatible cameras found.")
    else:
        for idx, dev in enumerate(device_list):
            print(f"  [{idx}] {dev.name} - {dev.serial}")

        # Step 4: Open the first device
        grabber.open_device(device_list[0])
        print(f"✅ Opened device: {device_list[0].name}")

        # Step 5: Get Auto Exposure property
        ae_property = grabber.get_property("Exposure Auto")
        if ae_property:
            print("🔎 Auto Exposure:", ae_property.get_value())
        else:
            print("⚠️ 'Exposure Auto' property not found.")

except Exception as e:
    print("❌ Error:", e)
