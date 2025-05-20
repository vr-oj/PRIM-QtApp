import json
import platform
import ctypes
import os
import imagingcontrol4 as ic4


def main():
    # System info
    report = {
        "system": {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "architecture": platform.machine(),
        },
        "library": {},
        "devices": [],
    }

    # ImagingControl4 version
    try:
        lib = ic4.Library.core
        # If version attribute exists
        ver = getattr(ic4.Library, "__version__", None)
        report["library"]["imagingcontrol4_version"] = ver
    except Exception:
        report["library"]["imagingcontrol4_version"] = None

    # Enumerate devices
    try:
        devs = ic4.DeviceEnum.devices()
        for dev in devs:
            pm = ic4.Grabber().device_open(dev) or ic4.Grabber().device_property_map
            props = {}
            for prop in pm:
                try:
                    props[prop.name] = {
                        "value": prop.value,
                        "min": getattr(prop, "minimum", None),
                        "max": getattr(prop, "maximum", None),
                        "type": type(prop).__name__,
                    }
                except Exception:
                    continue
            report["devices"].append(
                {
                    "model": dev.model_name,
                    "serial": dev.serial,
                    "properties": props,
                }
            )
    except Exception as e:
        print(f"Error enumerating devices: {e}")

    # Write report to file
    out_path = os.path.join(os.path.dirname(__file__), "camera_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"Wrote camera report to {out_path!r}")


if __name__ == "__main__":
    main()
