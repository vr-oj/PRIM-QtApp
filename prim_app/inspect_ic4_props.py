# inspect_ic4_props.py
import imagingcontrol4 as ic4


def main():
    print("Initializing IC4…")
    ic4.Library.init()

    print("Enumerating devices…")
    devices = ic4.DeviceEnum.devices()
    if not devices:
        print("No cameras found.")
        return

    dev = devices[0]
    print(f"\nOpening camera: {dev.model_name}")

    with ic4.Grabber(dev) as grabber:
        propmap = grabber.device_property_map

        print("\n=== FLOAT PROPERTIES ===")
        for name in propmap.float_names:
            try:
                prop = propmap.find_float(name)
                print(
                    f"- {name}: min={prop.min}, max={prop.max}, value={prop.value}, step={prop.inc}"
                )
            except Exception as e:
                print(f"- {name}: ERROR → {e}")

        print("\n=== INTEGER PROPERTIES ===")
        for name in propmap.integer_names:
            try:
                prop = propmap.find_integer(name)
                print(
                    f"- {name}: min={prop.min}, max={prop.max}, value={prop.value}, step={prop.inc}"
                )
            except Exception as e:
                print(f"- {name}: ERROR → {e}")

        print("\n=== ENUMERATION PROPERTIES ===")
        for name in propmap.enumeration_names:
            try:
                prop = propmap.find_enumeration(name)
                print(
                    f"- {name}: current={prop.value}, choices={[e.name for e in prop.entries]}"
                )
            except Exception as e:
                print(f"- {name}: ERROR → {e}")

    ic4.Library.exit()


if __name__ == "__main__":
    main()
