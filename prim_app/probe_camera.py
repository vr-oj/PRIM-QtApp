import imagingcontrol4 as ic4


def probe_first_camera():
    ic4.Library.init()  # ← make sure IC4 is initialized
    try:
        all_devs = ic4.DeviceEnum.devices()
        if len(all_devs) == 0:
            print("❌ No IC4 cameras found.")
            return

        dev = all_devs[0]
        print(f"Found camera: {dev.model_name} (SN {dev.serial})\n")

        grab = ic4.Grabber()
        grab.device_open(dev)

        # 1) Force the camera into “Continuous” mode (so PixelFormat changes are allowed)
        acq_mode_node = grab.device_property_map.find_enumeration("AcquisitionMode")
        if acq_mode_node is not None:
            try:
                acq_mode_node.value = "Continuous"
            except Exception as e:
                print(f"  • Warning: Could not force AcquisitionMode→Continuous: {e}")

        # 2) Locate the PixelFormat enumeration node
        pf_node = grab.device_property_map.find_enumeration("PixelFormat")
        if pf_node is None:
            print("❌ Could not find a ‘PixelFormat’ node at all.")
            grab.device_close()
            return

        print("Supported PixelFormat entries (attempting each)…\n")
        for entry in pf_node.entries:
            name = getattr(entry, "name", str(entry.value))
            val = entry.value
            print(
                f" → Trying PixelFormat = {name!r} (value={val}) … ", end="", flush=True
            )

            try:
                pf_node.value = val

                # If setting .value didn’t raise, read back width/height:
                w_node = grab.device_property_map.find_integer("ImageWidth")
                h_node = grab.device_property_map.find_integer("ImageHeight")
                if (w_node is None) or (h_node is None):
                    print("OK, but no ImageWidth/ImageHeight nodes found.")
                else:
                    w = w_node.value
                    h = h_node.value
                    print(f" OK → {w}×{h}")
            except Exception as e:
                print(f"─ failed: {e!s}")

        grab.device_close()

    finally:
        ic4.Library.exit()  # ← always clean up the library


if __name__ == "__main__":
    probe_first_camera()
