import imagingcontrol4 as ic4
from pprint import pprint


def main():
    print("🔧 Initializing IC4 Library...")
    ic4.Library.init()

    print("🔍 Enumerating devices...")
    devices = ic4.DeviceEnum.devices()
    pprint(devices)

    if not devices:
        print("❌ No devices found.")
        return

    device_info = devices[0]
    print(f"✅ Using device: {device_info.model_name} (Serial: {device_info.serial})")

    grabber = ic4.Grabber()
    grabber.open(device_info)

    print("\n📜 Device Property Names:")
    pm = grabber.device_property_map()
    names = pm.list_names()
    pprint(names)

    for name in names:
        try:
            prop = pm.find(name)
            print(f"\n🔧 Property: {name}")
            print(f"  Type: {type(prop)}")
            pprint(dir(prop))
        except Exception as e:
            print(f"⚠️ Failed to query {name}: {e}")

    print("\n✅ Done.")
    ic4.Library.exit()


if __name__ == "__main__":
    main()
