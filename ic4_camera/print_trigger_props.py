# print_trigger_props.py
import imagingcontrol4 as ic4


def main():
    ic4.Library.init(api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR)
    devices = ic4.DeviceEnum.devices()
    if not devices:
        print("No devices found.")
        ic4.Library.exit()
        return

    dev = devices[0]
    grabber = ic4.Grabber()
    grabber.device_open(dev)
    print(f"Opened camera: {dev.model_name} (S/N {dev.serial})")

    # Iterate over all properties; if it’s an enumeration, print its entries
    for prop in grabber.device_property_map:
        try:
            enum_node = grabber.device_property_map.find_enumeration(prop.id)
            if enum_node:
                values = [entry.name for entry in enum_node.entries]
                print(f"PropId {prop.id.name} → values = {values}")
        except Exception:
            pass

    grabber.device_close()
    ic4.Library.exit()


if __name__ == "__main__":
    main()
