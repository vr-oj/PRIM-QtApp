# File: dump_camera_capabilities.py

import imagingcontrol4 as ic4


def main():
    # 1) Initialize IC4
    try:
        ic4.Library.init()
    except ic4.IC4Exception as e:
        print("Library.init() failed:", e)
        return

    # 2) Enumerate devices and open the first one
    try:
        devices = ic4.DeviceEnum.devices()
    except ic4.IC4Exception as e:
        print("DeviceEnum.devices() failed:", e)
        return

    if not devices:
        print("No IC4 cameras found.")
        return

    info = devices[0]
    print(f"Opening camera: {info.model_name}")
    try:
        grabber = ic4.Grabber()
        grabber.device_open(info)
    except ic4.IC4Exception as e:
        print("Failed to open camera:", e)
        return

    pm = grabber.device_property_map

    # 3) Loop over every PropId constant
    all_prop_ids = [name for name in dir(ic4.PropId) if not name.startswith("_")]
    print(
        f"\nCamera reports {len(all_prop_ids)} PropId constants. Checking each one:\n"
    )

    for pid_name in all_prop_ids:
        pid = getattr(ic4.PropId, pid_name)
        print(f"--- {pid_name} ---")

        # A) Boolean?
        try:
            prop_bool = pm.find_boolean(pid)
            print("  Type: Boolean")
            print(f"    Current value = {prop_bool.value}")
            continue
        except ic4.IC4Exception:
            pass

        # B) Integer?
        try:
            prop_int = pm.find_integer(pid)
            vals = sorted(list(prop_int.valid_value_set))
            print("  Type: Integer")
            print(f"    Current value = {prop_int.value}")
            print(
                f"    Valid values (first/last 3) = {vals[:3]} … {vals[-3:]}  (count = {len(vals)})"
            )
            continue
        except ic4.IC4Exception:
            pass

        # C) Enumeration?
        try:
            prop_enum = pm.find_enumeration(pid)
            print("  Type: Enumeration")
            # Current selection as a plain string:
            curr = prop_enum.selected_entry.name
            print(f"    Current value = '{curr}'")
            # All valid options as plain strings:
            opts = [e.name for e in prop_enum.entries]
            print(f"    Options = {opts}")
            continue
        except ic4.IC4Exception:
            pass

        # D) Float?
        try:
            prop_float = pm.find_float(pid)
            print("  Type: Float")
            print(f"    Current value = {prop_float.value}")
            continue
        except ic4.IC4Exception:
            pass

        # E) String?
        try:
            prop_str = pm.find_string(pid)
            print("  Type: String")
            print(f"    Current value = '{prop_str.value}'")
            continue
        except ic4.IC4Exception:
            pass

        # F) Not implemented
        print("  Not supported by this camera.")

    # 4) Cleanup
    try:
        grabber.acquisition_stop()
    except:
        pass
    grabber.device_close()


if __name__ == "__main__":
    main()
