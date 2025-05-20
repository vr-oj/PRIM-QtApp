#!/usr/bin/env python3
import json, sys
import imagingcontrol4 as ic4


def dump_prop(p):
    info = {"value": None}
    try:
        info.update(
            {
                "type": type(p).__name__,
                "available": p.is_available,
                "readonly": getattr(p, "is_readonly", False),
            }
        )
        if hasattr(p, "entries"):
            info["entries"] = [e.name for e in p.entries]
        for attr in ("minimum", "maximum", "increment", "value"):
            if hasattr(p, attr):
                try:
                    info[attr] = getattr(p, attr)
                except Exception:
                    info[attr] = f"<error reading {attr}>"
    except Exception as e:
        info["error"] = str(e)
    return info


def main():
    ic4.Library.init()
    devices = ic4.DeviceEnum.devices()
    if not devices:
        print("No cameras found", file=sys.stderr)
        sys.exit(1)

    report = []
    for dev in devices:
        dev_report = {"model": dev.model_name, "serial": dev.serial, "properties": {}}
        grabber = ic4.Grabber()
        grabber.device_open(dev)
        pm = grabber.device_property_map

        for name in pm.property_names:
            try:
                p = pm.find(name)
                dev_report["properties"][name] = dump_prop(p)
            except Exception as e:
                dev_report["properties"][name] = {"error": str(e)}
        grabber.device_close()
        report.append(dev_report)

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
