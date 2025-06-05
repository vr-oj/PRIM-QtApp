# debug_ic4_api.py (Final Fallback)

import imagingcontrol4 as ic4

try:
    ic4.Library.init()
    print("✅ Library initialized")

    grabber = ic4.Grabber()
    print("✅ Grabber created")

    # Try opening any available device by guessing
    try:
        grabber.open_device("DMK 33UX250")  # or "DMK 33UP5000"
        print("✅ Opened device: DMK 33UX250")
    except Exception as e:
        print("❌ Failed to open device by name:", e)

    # Try property map access instead of get_property()
    try:
        prop_map = grabber.get_property_map()
        if "Exposure Auto" in prop_map:
            prop = prop_map["Exposure Auto"]
            print("🔎 Exposure Auto value:", prop.get_value())
        else:
            print("⚠️ 'Exposure Auto' property not found in map.")
    except Exception as e:
        print("❌ Failed to access properties:", e)

except Exception as e:
    print("❌ Top-level error:", e)
