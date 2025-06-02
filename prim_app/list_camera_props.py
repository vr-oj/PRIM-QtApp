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
    print(f"Opening camera: {info.model_name}  (serial: {info.serial_number})")

    try:
        grabber = ic4.Grabber()
        grabber.device_open(info)
    except ic4.IC4Exception as e:
        print("Failed to open camera:", e)
        return

    pm = grabber.device_property_map

    # The DevicePropertyMap doesn't have a direct "list all IDs" method,
    # but we can iterate over the PropId enum and try to query each one.
    # PropId is an enum; we can do something like `for prop_id in ic4.PropId:`
    # However, imagingcontrol4's Python wrapper does not expose `PropId` as a simple iterable.
    # Instead, we’ll grab every attribute name of ic4.PropId, filter out private names, and try them.
    all_prop_ids = [p for p in dir(ic4.PropId) if not p.startswith("_")]
    print("\nEnumerating properties:")
    for pid_name in all_prop_ids:
        # Skip the non-member attributes of PropId
        try:
            pid = getattr(ic4.PropId, pid_name)
        except AttributeError:
            continue

        # Attempt to fetch as boolean
        try:
            prop_bool = pm.find_boolean(pid)
            print(f"\n• PropBoolean {pid_name}: current value = {prop_bool.value}")
            continue
        except ic4.IC4Exception:
            pass

        # Attempt to fetch as integer
        try:
            prop_int = pm.find_integer(pid)
            vals = sorted(list(prop_int.valid_value_set))
            print(
                f"\n• PropInteger {pid_name}: current = {prop_int.value}, valid = [{vals[0]}, {vals[-1]}] (count={len(vals)})"
            )
            # If you want the entire set, uncomment:
            # print("    valid_value_set =", vals)
            continue
        except ic4.IC4Exception:
            pass

        # Attempt to fetch as enumeration
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

        # Attempt to fetch as float (some props are floats)
        try:
            prop_float = pm.find_float(pid)
            print(f"\n• PropFloat {pid_name}: current = {prop_float.value:.3f}")
            continue
        except ic4.IC4Exception:
            pass

        # If none of the above, just note it’s unsupported
        # (we skip properties that the camera does not actually implement)
        # print(f"\n• PropId {pid_name}: not supported on this camera.")

    # Finally, close everything
    try:
        grabber.acquisition_stop()
    except:
        pass
    grabber.device_close()


if __name__ == "__main__":
    main()
