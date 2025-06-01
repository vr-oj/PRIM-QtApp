import imagingcontrol4 as ic4


def print_property(prop_name, prop):
    try:
        value = prop.value
        min_val, max_val = prop.range
        print(f"  - {prop_name}: {value} (Range: {min_val}–{max_val})")
    except Exception as e:
        print(f"  - {prop_name}: ❌ Error reading -> {e}")


def main():
    print("📷 Starting IC4 property test...\n")

    ic4.Library.init(api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR)

    try:
        devices = ic4.DeviceEnum.devices()
        if not devices:
            print("❌ No devices found.")
            return

        device = devices[0]
        print(f"✅ Found device: {device.model_name} (Serial: {device.serial})")

        grabber = ic4.Grabber()
        grabber.device_open(device)
        print("✅ Camera opened successfully.\n")

        prop_map = grabber.get_property_map()
        print("📋 Available properties:\n")

        for prop_name in ["Gain", "Brightness", "ExposureTime", "AutoExposure"]:
            if prop_map.has_property(prop_name):
                prop = prop_map.get_property(prop_name)
                print_property(prop_name, prop)
            else:
                print(f"  - {prop_name}: ❌ Not supported by this device")

    except Exception as e:
        print(f"❌ ERROR: {e}")
    finally:
        ic4.Library.exit()
        print("\n✅ Library shut down.")


if __name__ == "__main__":
    main()
