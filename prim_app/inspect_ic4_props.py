from imagingcontrol4 import Library, DeviceEnum

# Initialize IC4
Library.init()
devices = DeviceEnum.devices()
if not devices:
    print("No IC4 cameras detected.")
    exit(1)

dev = devices[0]
print(f"Opening camera: {dev.model_name}")

with dev.open() as cam:
    props = cam.device_property_map

    for name in ["ExposureTime", "Gain", "Brightness"]:
        try:
            prop = props.find_float(name)
            print(f"\n=== {name} ===")
            print("dir(prop):", dir(prop))
            print("vars(prop):", vars(prop))  # sometimes works on ctypes-based objects
            print("range_min:", getattr(prop, "range_min", "N/A"))
            print("range_max:", getattr(prop, "range_max", "N/A"))
            print("inc:", getattr(prop, "inc", "N/A"))
            print("value:", getattr(prop, "value", "N/A"))
        except Exception as e:
            print(f"{name} lookup failed: {e}")

Library.exit()
