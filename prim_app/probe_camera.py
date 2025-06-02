import imagingcontrol4 as ic4


def probe_first_camera():
    # ─── 1) Initialize the IC4 library ───────────────────────────────
    ic4.Library.init()
    try:
        # ─── 2) Get the list of attached camera(s) ─────────────────────
        dev_list = ic4.DeviceEnum.devices()
        if not dev_list:
            print("No IC4 cameras detected.")
            return

        dev = dev_list[0]
        print(f"Found camera: {dev.model_name} (SN {dev.serial})\n")

        grab = ic4.Grabber()
        grab.device_open(dev)

        # ─── 3) Force “Continuous” AcquisitionMode (if present) ────────
        acq_node = grab.device_property_map.find_enumeration("AcquisitionMode")
        if acq_node is not None:
            names = [e.name for e in acq_node.entries]
            print("Available AcquisitionMode entries:", names)
            # Try setting “Continuous” if it exists, otherwise pick the first
            if "Continuous" in names:
                acq_node.value = "Continuous"
                print("→ Set AcquisitionMode = 'Continuous'\n")
            else:
                acq_node.value = names[0]
                print(f"→ Set AcquisitionMode = '{names[0]}' (fallback)\n")
        else:
            print("  (No ‘AcquisitionMode’ node found.)\n")

        # ─── 4) Find PixelFormat enumeration node ───────────────────────
        pf_node = grab.device_property_map.find_enumeration("PixelFormat")
        if pf_node is None:
            print("No ‘PixelFormat’ node on this camera.")
            grab.device_close()
            return

        # Print all names for debugging:
        all_pf = [e.name for e in pf_node.entries]
        print("All PixelFormat entries (names):", all_pf, "\n")
        print("Supported PixelFormat → resolution:\n")

        # ─── 5) Try each PixelFormat by name, then read Width/Height ───
        for entry in pf_node.entries:
            name = entry.name
            print(f" → Trying PixelFormat = {name!r} … ", end="", flush=True)

            try:
                pf_node.value = name

                # Read back “Width”/“Height” (not ImageWidth/ImageHeight)
                w_prop = grab.device_property_map.find_integer("Width")
                h_prop = grab.device_property_map.find_integer("Height")

                if (w_prop is None) or (h_prop is None):
                    print("OK (but no Width/Height nodes to query).")
                else:
                    w = w_prop.value
                    h = h_prop.value
                    print(f"OK → {w}×{h}")

            except Exception as e:
                print(f"── failed: {e!s}")

        grab.device_close()

    finally:
        # ─── 6) Tear down IC4 ───────────────────────────────────────────
        ic4.Library.exit()


if __name__ == "__main__":
    probe_first_camera()
