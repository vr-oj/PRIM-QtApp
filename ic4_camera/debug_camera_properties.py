import imagingcontrol4 as ic4


def cycle_over_props(pm):
    # Intentionally include some debug prints of pid and its type:
    enum_pids = [
        ic4.PropId.EXPOSURE_AUTO,
        ic4.PropId.GAIN_AUTO,
        ic4.PropId.PIXEL_FORMAT,
        ic4.PropId.TRIGGER_MODE,
        ic4.PropId.TRIGGER_SOURCE,
    ]
    print("--- Debug: enum_pids contents and types ---")
    for pid in enum_pids:
        print(f"   pid = {pid!r},   type(pid) = {type(pid)}")
    print("-----------------------------------------")
    # (We won't toggle anything here—just inspect the list.)


def main():
    ic4.Library.init()
    devs = ic4.DeviceEnum.devices()
    if not devs:
        print("No cameras found.")
        return
    grab = ic4.Grabber()
    grab.device_open(devs[0])
    pm = grab.device_property_map

    cycle_over_props(pm)

    grab.acquisition_stop()
    grab.device_close()


if __name__ == "__main__":
    main()
