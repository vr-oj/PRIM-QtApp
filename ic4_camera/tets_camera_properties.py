import time
import imagingcontrol4 as ic4


def toggle_enumeration(pm, pid):
    """Find an enumeration property, print its current value,
    switch to the next available entry (if any), then print again."""
    try:
        prop = pm.find_enumeration(pid)
    except ic4.IC4Exception:
        print(f"  [SKIP] {pid.name}: not an enumeration on this camera.")
        return

    entries = [e.name for e in prop.entries]
    curr = prop.selected_entry.name
    print(f"  {pid.name}: current = '{curr}' (options: {entries})")
    if len(entries) < 2:
        print(f"    Only one option – cannot toggle.\n")
        return

    # Pick the next entry in the list (wrap around)
    idx = entries.index(curr)
    new = entries[(idx + 1) % len(entries)]
    prop.selected_entry = new
    # Give the camera a moment to apply
    time.sleep(0.1)
    print(f"    Toggled → now = '{prop.selected_entry.name}'\n")


def toggle_boolean(pm, pid):
    """Find a boolean property, print its current value,
    flip it, then print again."""
    try:
        prop = pm.find_boolean(pid)
    except ic4.IC4Exception:
        print(f"  [SKIP] {pid.name}: not a boolean on this camera.")
        return

    curr = prop.value
    print(f"  {pid.name}: current = {curr}")
    prop.value = not curr
    time.sleep(0.1)
    print(f"    Toggled → now = {prop.value}\n")


def adjust_float(pm, pid):
    """Find a float property, print current value,
    set it to mid‐range between its auto‐limits (if available),
    then print again."""
    try:
        prop = pm.find_float(pid)
    except ic4.IC4Exception:
        print(f"  [SKIP] {pid.name}: not a float on this camera.")
        return

    curr = prop.value
    print(f"  {pid.name}: current = {curr}")

    # Try to get auto‐limits if they exist
    lower, upper = None, None
    # Common pattern: look for PID + "_LOWER_LIMIT" and "_UPPER_LIMIT"
    # in PropId (e.g. EXPOSURE_AUTO_LOWER_LIMIT). If available, use them.
    name_low = pid.name + "_LOWER_LIMIT"
    name_up = pid.name + "_UPPER_LIMIT"
    ll, ul = None, None
    if hasattr(ic4.PropId, name_low) and hasattr(ic4.PropId, name_up):
        try:
            ll = pm.find_float(getattr(ic4.PropId, name_low)).value
            ul = pm.find_float(getattr(ic4.PropId, name_up)).value
        except ic4.IC4Exception:
            ll, ul = None, None

    if ll is not None and ul is not None and ul > ll:
        mid = (ll + ul) / 2.0
        print(f"    Using auto‐limits: {ll} … {ul}, setting mid = {mid}")
        prop.value = mid
    else:
        # If no valid auto‐limits, just add/subtract 10 % to current
        mid = curr * 1.1 if curr > 0 else 1.0
        print(f"    No auto‐limits found. Setting to {mid}")
        prop.value = mid

    time.sleep(0.1)
    print(f"    New {pid.name} = {prop.value}\n")


def cycle_over_props(pm):
    print("\n=== Testing Enumeration Props ===")
    enum_pids = [
        ic4.PropId.EXPOSURE_AUTO,
        ic4.PropId.GAIN_AUTO,
        ic4.PropId.PIXEL_FORMAT,
        ic4.PropId.TRIGGER_MODE,
        ic4.PropId.TRIGGER_SOURCE,
    ]
    for pid in enum_pids:
        toggle_enumeration(pm, pid)

    print("=== Testing Boolean Props ===")
    bool_pids = [
        ic4.PropId.AUTO_FUNCTIONS_ROI_ENABLE,
        ic4.PropId.CHUNK_ENABLE,
        ic4.PropId.LUT_ENABLE,
        ic4.PropId.SOFTWARE_TRANSFORM_ENABLE,
    ]
    for pid in bool_pids:
        toggle_boolean(pm, pid)

    print("=== Testing Float Props ===")
    float_pids = [
        ic4.PropId.EXPOSURE_TIME,
        ic4.PropId.ACQUISITION_FRAME_RATE,
        ic4.PropId.DEVICE_TEMPERATURE,
        ic4.PropId.GAIN,
    ]
    for pid in float_pids:
        adjust_float(pm, pid)


def main():
    print("Initializing IC4…")
    try:
        ic4.Library.init()
    except ic4.IC4Exception as e:
        print("Library.init() failed:", e)
        return

    print("Enumerating devices…")
    try:
        devices = ic4.DeviceEnum.devices()
    except ic4.IC4Exception as e:
        print("DeviceEnum.devices() failed:", e)
        return

    if not devices:
        print("No IC4 cameras found.")
        return

    info = devices[0]
    print(f"Opening camera: {info.model_name}\n")
    try:
        grabber = ic4.Grabber()
        grabber.device_open(info)
    except ic4.IC4Exception as e:
        print("Failed to open camera:", e)
        return

    pm = grabber.device_property_map

    # 1) Print some basics:
    print("=== Basic Camera Info ===")
    try:
        model = pm.find_string(ic4.PropId.DEVICE_MODEL_NAME).value
        serial = pm.find_string(ic4.PropId.DEVICE_SERIAL_NUMBER).value
        temp = pm.find_float(ic4.PropId.DEVICE_TEMPERATURE).value
        print(f"  Model   = {model}")
        print(f"  Serial  = {serial}")
        print(f"  Temp    = {temp:.1f} °C\n")
    except ic4.IC4Exception:
        pass

    # 2) Cycle through enumerations/booleans/floats
    cycle_over_props(pm)

    # 3) Cleanup
    try:
        grabber.acquisition_stop()
    except:
        pass
    grabber.device_close()
    print("Done.")


if __name__ == "__main__":
    main()
