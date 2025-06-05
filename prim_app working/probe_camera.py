# probe_camera.py
import imagingcontrol4 as ic4


def probe_first_camera():
    # ─── Initialize IC4 ──────────────────────────────────────
    ic4.Library.init()
    try:
        dev_list = ic4.DeviceEnum.devices()
        if not dev_list:
            print("No IC4 cameras detected.")
            return

        dev = dev_list[0]
        print(f"Found camera: {dev.model_name} (SN {dev.serial})\n")

        grab = ic4.Grabber()
        grab.device_open(dev)

        # ─── Force “Continuous” AcquisitionMode (if it exists) ──
        acq_node = grab.device_property_map.find_enumeration("AcquisitionMode")
        if acq_node is not None:
            names = [e.name for e in acq_node.entries]
            print("Available AcquisitionMode entries:", names)
            if "Continuous" in names:
                acq_node.value = "Continuous"
                print("→ Set AcquisitionMode = 'Continuous'\n")
            else:
                acq_node.value = names[0]
                print(f"→ Set AcquisitionMode = '{names[0]}' (fallback)\n")
        else:
            print("  (No ‘AcquisitionMode’ node found.)\n")

        # ─── Find PixelFormat and enumerate resolutions ───────────
        pf_node = grab.device_property_map.find_enumeration("PixelFormat")
        if pf_node is None:
            print("No ‘PixelFormat’ node on this camera.")
            grab.device_close()
            return

        all_pf = [e.name for e in pf_node.entries]
        print("All PixelFormat entries (names):", all_pf, "\n")
        print("Supported PixelFormat → resolution:\n")

        for entry in pf_node.entries:
            name = entry.name
            print(f" → Trying PixelFormat = '{name}' … ", end="", flush=True)
            try:
                pf_node.value = name
                w_prop = grab.device_property_map.find_integer("Width")
                h_prop = grab.device_property_map.find_integer("Height")
                if (w_prop is None) or (h_prop is None):
                    print("OK (no Width/Height nodes found).")
                else:
                    w = w_prop.value
                    h = h_prop.value
                    print(f"OK → {w}×{h}")
            except Exception as e:
                print(f"── failed: {e!s}")

        grab.device_close()

    finally:
        ic4.Library.exit()


if __name__ == "__main__":
    probe_first_camera()
