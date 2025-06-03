import imagingcontrol4 as ic4

ic4.Library.init()
devs = ic4.DeviceEnum.devices()
grab = ic4.Grabber()
grab.device_open(devs[0])
pm = grab.device_property_map

for pid_name in [n for n in dir(ic4.PropId) if not n.startswith("_")]:
    pid = getattr(ic4.PropId, pid_name)
    print(f"--- {pid_name} ---")

    # Boolean?
    try:
        b = pm.find_boolean(pid)
        print("  Type: Boolean")
        print(f"    Current value = {b.value}")
        continue
    except ic4.IC4Exception:
        pass

    # Integer?
    try:
        i = pm.find_integer(pid)
        vals = sorted(list(i.valid_value_set))
        print("  Type: Integer")
        print(f"    Current value = {i.value}")
        print(f"    Valid values = {vals[:3]} … {vals[-3:]}  (count = {len(vals)})")
        continue
    except ic4.IC4Exception:
        pass

    # Enumeration?
    try:
        e = pm.find_enumeration(pid)
        print("  Type: Enumeration")
        print(f"    Current value = '{e.selected_entry}'")
        print(f"    Options = {e.entries}")
        continue
    except ic4.IC4Exception:
        pass

    # Float?
    try:
        f = pm.find_float(pid)
        print("  Type: Float")
        print(f"    Current value = {f.value}")
        continue
    except ic4.IC4Exception:
        pass

    # String?
    try:
        s = pm.find_string(pid)
        print("  Type: String")
        print(f"    Current value = '{s.value}'")
        continue
    except ic4.IC4Exception:
        pass

    # Not supported
    print("  Not supported by this camera.")

grab.acquisition_stop()
grab.device_close()
