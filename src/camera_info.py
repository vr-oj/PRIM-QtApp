#!/usr/bin/env python3
import json
import sys
import platform
import imagingcontrol4 as ic4


def dump_prop(p):
    info = {
        "type": type(p).__name__,
        "available": getattr(p, "is_available", False),
        "readonly": getattr(p, "is_readonly", False),
        "value": None,
    }
    # Enumeration entries
    if hasattr(p, "entries"):
        try:
            info["entries"] = [e.name for e in p.entries]
        except Exception:
            info["entries"] = "<error reading entries>"

    # Numeric limits & increment
    for attr in ("minimum", "maximum", "increment", "value"):
        if hasattr(p, attr):
            try:
                info[attr] = getattr(p, attr)
            except Exception:
                info[attr] = f"<error reading {attr}>"
    return info


def main():
    # 1) Init library
    try:
        ic4.Library.init()
    except Exception:
        # already initialized? ignore
        pass

    # 2) Base report structure
    report = {
        "system": {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "architecture": platform.machine(),
        },
        "library": {
            # if the binding exposes a version API
            "imagingcontrol4_version": getattr(ic4.Library, "version", lambda: None)()
        },
        "devices": [],
    }

    # 3) Enumerate cameras
    devices = ic4.DeviceEnum.devices()
    if not devices:
        print("No cameras found", file=sys.stderr)
        sys.exit(1)

    # 4) For each device, open & scrape its PropertyMap
    for dev in devices:
        dev_report = {"model": dev.model_name, "serial": dev.serial, "properties": {}}
        grabber = ic4.Grabber()
        grabber.device_open(dev)
        pm = grabber.device_property_map

        # 5) Enumerate all property names by inspecting pm.properties dict
        #    (PropertyMap.properties is a dict of name→Prop*)
        try:
            prop_names = list(pm.properties.keys())
        except Exception:
            prop_names = []

        for name in prop_names:
            try:
                prop = pm.find(name)
                dev_report["properties"][name] = dump_prop(prop)
            except Exception as e:
                dev_report["properties"][name] = {"error": str(e)}

        grabber.device_close()
        report["devices"].append(dev_report)

    # 6) Print JSON
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
