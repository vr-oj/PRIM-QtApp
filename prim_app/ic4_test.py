import imagingcontrol4 as ic4


def format_device_info(device_info: ic4.DeviceInfo) -> str:
    return f"Model: {device_info.model_name}, Serial: {device_info.serial}"


def print_device_list():
    print("\n🔍 Enumerating all attached video capture devices...\n")
    try:
        devices = ic4.DeviceEnum.devices()
        if not devices:
            print("❌ No devices found.\n")
        else:
            print(f"✅ Found {len(devices)} device(s):")
            for device in devices:
                print(f" - {format_device_info(device)}")
    except Exception as e:
        print(f"❌ Error getting device list: {e}")


def print_interface_device_tree():
    print("\n📡 Enumerating video capture devices by interface...\n")
    try:
        interfaces = ic4.DeviceEnum.interfaces()
        if not interfaces:
            print("❌ No interfaces found.\n")
            return

        for interface in interfaces:
            print(f"Interface: {interface.display_name}")
            print(
                f"  ↳ Transport Layer: {interface.transport_layer_name} ({interface.transport_layer_type})"
            )
            for device in interface.devices:
                print(f"    - {format_device_info(device)}")
    except Exception as e:
        print(f"❌ Error getting interfaces: {e}")


def main():
    print("✅ Starting IC4 test...")

    try:
        ic4.Library.init(
            api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR
        )
        print("✅ IC4 Library initialized")
        print_device_list()
        print_interface_device_tree()
    except Exception as e:
        print(f"❌ Error during IC4 test: {e}")
    finally:
        ic4.Library.exit()
        print("\n✅ IC4 Library shut down cleanly.")


if __name__ == "__main__":
    main()
