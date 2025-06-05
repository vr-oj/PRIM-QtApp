# File: list_camera_props.py

import imagingcontrol4 as ic4


def main():
    try:
        ic4.Library.init()
    except ic4.IC4Exception as e:
        print("Library.init() failed:", e)
        return

    try:
        devices = ic4.DeviceEnum.devices()
    except ic4.IC4Exception as e:
        print("DeviceEnum.devices() failed:", e)
        return

    if not devices:
        print("No IC4 cameras found.")
        return

    # Just pick the first device in the list
    info = devices[0]
    print(f"Opening camera: {info.model_name}")

    try:
        grabber = ic4.Grabber()
        grabber.device_open(info)
    except ic4.IC4Exception as e:
        print("Failed to open camera:", e)
        return

    pm = grabber.device_property_map

    # PropId is not directly iterable, so iterate over its attributes
    all_prop_ids = [p for p in dir(ic4.PropId) if not p.startswith("_")]
    print("\nEnumerating supported properties:")
    for pid_name in all_prop_ids:
        pid = getattr(ic4.PropId, pid_name, None)
        if pid is None:
            continue

        # Try PropBoolean
        try:
            prop_bool = pm.find_boolean(pid)
            print(f"\n• PropBoolean {pid_name}: current = {prop_bool.value}")
            continue
        except ic4.IC4Exception:
            pass

        # Try PropInteger
        try:
            prop_int = pm.find_integer(pid)
            vals = sorted(list(prop_int.valid_value_set))
            print(
                f"\n• PropInteger {pid_name}: current = {prop_int.value}, "
                f"valid range = [{vals[0]} .. {vals[-1]}], count={len(vals)}"
            )
            continue
        except ic4.IC4Exception:
            pass

        # Try PropEnumeration
        try:
            prop_enum = pm.find_enumeration(pid)
            entries = prop_enum.valid_value_strings
            current = prop_enum.value_string
            print(
                f"\n• PropEnumeration {pid_name}: current = '{current}', options = {entries}"
            )
            continue
        except ic4.IC4Exception:
            pass

        # Try PropFloat
        try:
            prop_float = pm.find_float(pid)
            print(f"\n• PropFloat {pid_name}: current = {prop_float.value:.3f}")
            continue
        except ic4.IC4Exception:
            pass

        # If none matched, the camera doesn’t implement this PropId (skip it)
        # print(f"• PropId {pid_name}: NOT supported")

    # Close camera
    try:
        grabber.acquisition_stop()
    except:
        pass
    grabber.device_close()


if __name__ == "__main__":
    main()
