import imagingcontrol4 as ic4


def probe_first_camera():
    ic4.Library.init()
    try:
        devs = ic4.DeviceEnum.devices()
        if len(devs) == 0:
            print("No IC4 cameras found at all.")
            return

        print(f"Found camera: {devs[0].model_name} (SN {devs[0].serial})")
        grab = ic4.Grabber()
        grab.device_open(devs[0])

        pf_node = grab.device_property_map.find_enumeration("PixelFormat")
        if not pf_node:
            print("❌ PixelFormat node not found!")
            grab.device_close()
            return

        print("Supported pixel formats and resolutions:")
        for entry in pf_node.entries:
            try:
                pf_node.value = entry.value
            except Exception:
                # skip formats that aren’t available right now
                continue

            w_node = grab.device_property_map.find_integer("ImageWidth")
            h_node = grab.device_property_map.find_integer("ImageHeight")
            if (w_node is None) or (h_node is None):
                continue

            w = w_node.value
            h = h_node.value
            fmt_name = getattr(entry, "name", str(entry.value))
            print(f"  • {w}×{h}  → {fmt_name}  (value={entry.value})")

        grab.device_close()

    finally:
        ic4.Library.exit()


if __name__ == "__main__":
    probe_first_camera()
