#!/usr/bin/env python3
import imagingcontrol4 as ic4
from imagingcontrol4.properties import PropEnumeration, PropInteger, PropFloat
import platform, json, sys, traceback

CAMERA_PROPS = [
    "PixelFormat",
    "Width",
    "Height",
    "OffsetX",
    "OffsetY",
    "AcquisitionMode",
    "TriggerMode",
    "AcquisitionFrameRate",
    "ExposureAuto",
    "ExposureTime",
    "Gain",
]


def dump_prop(pm, name):
    p = pm.find(name)
    if p is None:
        return None
    info = {
        "type": type(p).__name__,
        "available": bool(p.is_available),
        "readonly": bool(getattr(p, "is_readonly", False)),
        "value": p.value if hasattr(p, "value") else None,
    }
    if isinstance(p, (PropInteger, PropFloat)):
        info.update(
            minimum=p.minimum,
            maximum=p.maximum,
            increment=getattr(p, "increment", None),
        )
    if isinstance(p, PropEnumeration):
        info["entries"] = [e.name for e in p.entries]
    return info


def main():
    report = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "qt": "PyQt5",
        "imagingcontrol4": getattr(ic4.Library, "version", "n/a"),
        "devices": [],
    }

    # make sure library is initialized once
    try:
        ic4.Library.init()
    except Exception:
        pass

    for dev in ic4.DeviceEnum.devices():
        entry = {
            "model": dev.model_name,
            "serial": dev.serial,
            "version": dev.version,
            "open_succeeded": False,
            "properties": {},
            "error": None,
        }
        grabber = ic4.Grabber()
        try:
            grabber.device_open(dev)
            entry["open_succeeded"] = True
            pm = grabber.device_property_map
            for name in CAMERA_PROPS:
                pinfo = dump_prop(pm, name)
                if pinfo is not None:
                    entry["properties"][name] = pinfo
        except Exception as e:
            # if it's in use, just note it and continue
            entry["error"] = traceback.format_exc()
        finally:
            try:
                if entry["open_succeeded"]:
                    grabber.device_close()
            except:
                pass

        report["devices"].append(entry)

    json.dump(report, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
