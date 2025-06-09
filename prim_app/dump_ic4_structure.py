# File: dump_ic4_structure.py

import imagingcontrol4 as ic4
from pprint import pprint
from datetime import datetime
import sys

# Optional: Save output to a log file
log_path = f"ic4_dump_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
sys.stdout = open(log_path, "w", encoding="utf-8")


def main():
    print("🔧 Initializing IC4 Library...")
    ic4.Library.init()

    print("🔍 Enumerating devices...")
    devices = ic4.DeviceEnum.devices()
    if not devices:
        print("❌ No IC4 devices found.")
        return

    device = devices[0]
    print(f"✅ Using device: {device.model_name} (Serial: {device.serial})")

    grabber = ic4.Grabber()
    grabber.device = device

    print("\n📜 Device Property Names:")
    try:
        pm = grabber.device_property_map
        names = pm.list_names()
        for prop_name in sorted(names):
            print(f"── {prop_name} ──")
            try:
                prop = pm.get(prop_name)
                print(f"  Type: {type(prop).__name__}")
                if hasattr(prop, "is_writable"):
                    print(f"  Writable: {prop.is_writable}")
                if hasattr(prop, "unit"):
                    print(f"  Unit: {prop.unit}")
                if isinstance(prop, ic4.PropFloat):
                    print(f"  Min: {prop.min}, Max: {prop.max}, Increment: {prop.inc}")
                    print(f"  Value: {prop.value}")
                    if prop.is_writable:
                        try:
                            original = prop.value
                            test_value = max(prop.min, min(prop.max, original * 0.9))
                            prop.value = test_value
                            print(f"  ✔️ Test write: new value = {prop.value}")
                            prop.value = original  # restore
                        except Exception as e:
                            print(f"  ❌ Failed to write value: {e}")
                elif isinstance(prop, ic4.PropEnumeration):
                    entries = prop.entries()
                    print("  Entries:", [e.name for e in entries])
                    print(f"  Current: {prop.current.name}")
                elif isinstance(prop, ic4.PropInteger):
                    print(
                        f"  Value: {prop.value}, Min: {prop.min}, Max: {prop.max}, Inc: {prop.inc}"
                    )
                else:
                    print(f"  ⚠️ Unsupported type: {type(prop)}")
            except Exception as prop_err:
                print(f"  ⚠️ Error reading property: {prop_err}")
    except Exception as e:
        print("❌ Failed to read property map:", e)

    print("\n✅ Done.")
    ic4.Library.exit()


if __name__ == "__main__":
    main()
