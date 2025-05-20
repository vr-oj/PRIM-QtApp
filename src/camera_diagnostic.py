#!/usr/bin/env python3
import imagingcontrol4 as ic4
from imagingcontrol4.properties import PropEnumeration, PropInteger, PropFloat
import platform, json, sys, traceback

# the names you want to inspect
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
        "available": bool(p.is_available),
        "readonly": bool(getattr(p, "is_readonly", False)),
        "value": getattr(p, "value", None),
        "type": type(p).__name__,
    }
    if isinstance(p, PropInteger) or isinstance(p, PropFloat):
        for attr in ("minimum", "maximum", "increment"):
            info[attr] = getattr(p, attr, None)
    if isinstance(p, PropEnumeration):
        info["entries"] = [e.name for e in p.entries]
    return info


def main():
    report = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "qt_binding": "PyQt5",
        "imagingcontrol4": getattr(ic4.Library, "version", "n/a"),
        "devices": [],
    }

    # ensure library is inited
    try:
        ic4.Library.init()
    except Exception:
        pass

    devs = ic4.DeviceEnum.devices()
    for dev in devs:
        dev_entry = {
            "model": dev.model_name,
            "serial": dev.serial,
            "version": dev.version,
            "properties": {},
        }
        grabber = ic4.Grabber()
        try:
            grabber.device_open(dev)
            pm = grabber.device_property_map
            for name in CAMERA_PROPS:
                v = dump_prop(pm, name)
                if v is not None:
                    dev_entry["properties"][name] = v
        except Exception:
            dev_entry["error"] = traceback.format_exc()
        finally:
            try:
                grabber.device_close()
            except:
                pass

        report["devices"].append(dev_entry)

    json.dump(report, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
