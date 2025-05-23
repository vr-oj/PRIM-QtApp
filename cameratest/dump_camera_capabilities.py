#!/usr/bin/env python3
import os
import platform
import glob
from harvesters.core import Harvester

# --- Edit this to your .cti path or auto-discover like in your main.py ---
CTI_PATH = r"C:\Program Files\The Imaging Source Europe GmbH\IC4 GenTL Driver for USB3Vision Devices 1.4\bin\ic4-gentl-u3v_x64.cti"


def find_cti():
    if os.path.isfile(CTI_PATH):
        return CTI_PATH
    # Fallback: search Program Files
    prog_dirs = [
        os.environ.get("ProgramFiles", "C:\\Program Files"),
        os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
    ]
    for pd in prog_dirs:
        for root, _, files in os.walk(pd):
            for f in files:
                if f.lower().endswith(".cti") and "ic4" in f.lower():
                    return os.path.join(root, f)
    raise FileNotFoundError("Could not locate any .cti file")


def main():
    # Initialize
    h = Harvester()
    cti = find_cti()
    print(f"Using CTI: {cti}")
    h.add_file(cti)
    h.update()

    if not h.device_info_list:
        print("No cameras found!")
        return

    # Grab first camera
    ia = h.create(0)
    nm = ia.remote_device.node_map

    print("\n--- CAMERA CAPABILITIES DUMP ---\n")
    for name in sorted(n for n in dir(nm) if not n.startswith("_")):
        try:
            node = getattr(nm, name)
            node_type = node.__class__.__name__
            print(f"{name}  ({node_type})")

            # 1) Current value?
            if hasattr(node, "value"):
                try:
                    val = node.value
                    print(f"  Current value: {val}")
                except Exception as ex:
                    print(f"  Could not read value: {ex}")

            # 2) Numeric range?
            if all(hasattr(node, attr) for attr in ("min", "max", "increment")):
                try:
                    print(f"  Range: {node.min} … {node.max}, step {node.increment}")
                except Exception as ex:
                    print(f"  Could not read range: {ex}")

            # 3) Enum options?
            if hasattr(node, "symbolics"):
                try:
                    syms = node.symbolics
                    print(f"  Options: {syms}")
                except Exception as ex:
                    print(f"  Could not read options: {ex}")

            print()

        except Exception as node_ex:
            # Catch any unexpected error on this node and continue
            print(f"{name}: ERROR during introspection: {node_ex}\n")

    # Cleanup
    ia.destroy()
    h.reset()


if __name__ == "__main__":
    main()
