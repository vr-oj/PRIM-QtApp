import imagingcontrol4 as ic4


def probe_first_camera():
    # ─── Initialize IC4 ─────────────────────────────────────────────
    ic4.Library.init()
    try:
        device_list = ic4.DeviceEnum.devices()
        if not device_list:
            print("❌ No IC4 cameras found.")
            return

        dev = device_list[0]
        print(f"Found camera: {dev.model_name} (SN {dev.serial})\n")

        grab = ic4.Grabber()
        grab.device_open(dev)

        # ─── 1) Force “Continuous” acquisition mode ────────────────────
        acq_mode_node = grab.device_property_map.find_enumeration("AcquisitionMode")
        if acq_mode_node is not None:
            # Print available acquisition‐mode strings for debugging:
            all_modes = [e.name for e in acq_mode_node.entries]
            print("Available AcquisitionMode entries:", all_modes)
            # Try setting one of them—usually "Continuous" or "Video"
            try:
                acq_mode_node.value = "Continuous"
                print("→ Set AcquisitionMode = 'Continuous'")
            except Exception:
                # If “Continuous” fails, try first entry in the list:
                fallback = all_modes[0]
                acq_mode_node.value = fallback
                print(f"→ Set AcquisitionMode = '{fallback}' (fallback)")
        else:
            print("  • Warning: no ‘AcquisitionMode’ node found on this camera.")

        print("\nSupported PixelFormat entries (attempting each)…\n")

        # ─── 2) Find the PixelFormat node ───────────────────────────────
        pf_node = grab.device_property_map.find_enumeration("PixelFormat")
        if pf_node is None:
            print("❌ Could not find a ‘PixelFormat’ node at all.")
            grab.device_close()
            return

        # Print all enumeration‐names for PixelFormat:
        all_pf_names = [entry.name for entry in pf_node.entries]
        print("All PixelFormat entries (names):", all_pf_names)
        print("")

        # ─── 3) Try setting each PixelFormat by name ───────────────────
        for entry in pf_node.entries:
            name = entry.name
            print(f" → Trying PixelFormat = {name!r} … ", end="", flush=True)

            try:
                pf_node.value = name

                # If that succeeded, read back width & height:
                w_node = grab.device_property_map.find_integer("ImageWidth")
                h_node = grab.device_property_map.find_integer("ImageHeight")
                if (w_node is None) or (h_node is None):
                    print(" OK (but no ImageWidth/ImageHeight nodes).")
                else:
                    w = w_node.value
                    h = h_node.value
                    print(f" OK → {w}×{h}")

            except Exception as e:
                print(f"─ failed: {e!s}")

        grab.device_close()

    finally:
        # ─── 4) Clean up IC4 ─────────────────────────────────────────────
        ic4.Library.exit()


if __name__ == "__main__":
    probe_first_camera()
