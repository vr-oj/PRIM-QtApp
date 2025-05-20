import json
import platform
import ctypes
import sys
import imagingcontrol4 as ic4
from imagingcontrol4.properties import (
    PropInteger,
    PropFloat,
    PropEnumeration,
)

# Initialize the IC4 library
try:
    ic4.Library.init()
except Exception as e:
    # Already initialized or failed
    pass

# File to write report
REPORT_PATH = "camera_report.json"


def gather_system_info():
    return {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "architecture": platform.machine(),
    }


def gather_library_info():
    # imagingcontrol4 may not expose a version attribute; attempt safe lookup
    version = None
    try:
        version = ic4.Library.core.ic4_lib_version().decode("utf-8")
    except Exception:
        pass
    return {"imagingcontrol4_version": version}


def gather_device_info():
    devices = []
    try:
        devs = ic4.DeviceEnum.devices()
    except Exception as e:
        print(f"Error enumerating devices: {e}")
        devs = []

    for dev in devs:
        try:
            info = {
                "model": dev.model_name,
                "serial": dev.serial_number if hasattr(dev, "serial_number") else None,
                "properties": {},
            }
            grabber = ic4.Grabber()
            grabber.device_open(dev)
            pm = grabber.device_property_map
            # List a core set of GenICam properties
            for name in [
                "Height",
                "Width",
                "PixelFormat",
                "ExposureAuto",
                "ExposureTime",
                "Gain",
                "OffsetX",
                "OffsetY",
                "AcquisitionMode",
                "TriggerMode",
                "AcquisitionFrameRate",
            ]:
                try:
                    prop = pm.find(name)
                    if prop and prop.is_available:
                        pinfo = {"value": prop.value}
                        # Optional attributes
                        if hasattr(prop, "minimum"):
                            pinfo["min"] = prop.minimum
                        if hasattr(prop, "maximum"):
                            pinfo["max"] = prop.maximum
                        if hasattr(prop, "increment"):
                            pinfo["inc"] = prop.increment
                        if isinstance(prop, PropEnumeration):
                            pinfo["options"] = [e.name for e in prop.entries]
                        pinfo["readonly"] = getattr(prop, "is_readonly", False)
                        info["properties"][name] = pinfo
                except Exception:
                    pass
            grabber.device_close()
        except Exception:
            pass
        devices.append(info)
    return devices


def main():
    report = {
        "system": gather_system_info(),
        "library": gather_library_info(),
        "devices": gather_device_info(),
    }
    # Write JSON
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Wrote camera report to '{REPORT_PATH}'")


if __name__ == "__main__":
    main()
