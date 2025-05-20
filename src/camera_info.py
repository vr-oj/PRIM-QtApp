import os
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
except Exception:
    # Already initialized or unavailable
    pass

# Path to write report next to this script
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
REPORT_PATH = os.path.join(BASE_DIR, "camera_report.json")


def gather_system_info():
    return {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "architecture": platform.machine(),
    }


def gather_library_info():
    version = None
    try:
        # imagingcontrol4 C API version
        raw = ic4.Library.core.ic4_lib_version()
        if isinstance(raw, (bytes, bytearray)):
            version = raw.decode("utf-8", errors="ignore")
    except Exception:
        pass
    return {"imagingcontrol4_version": version}


def gather_device_info():
    devices = []
    try:
        devs = ic4.DeviceEnum.devices()
    except Exception as e:
        devs = []
    for dev in devs:
        info = {
            "model": dev.model_name,
            "serial": getattr(dev, "serial_number", None),
            "properties": {},
        }
        try:
            grabber = ic4.Grabber()
            grabber.device_open(dev)
            pm = grabber.device_property_map
            # probe fixed list of core GenICam props
            prop_names = [
                PROP_HEIGHT := "Height",
                PROP_WIDTH := "Width",
                PROP_PIXEL_FORMAT := "PixelFormat",
                PROP_EXPOSURE_AUTO := "ExposureAuto",
                PROP_EXPOSURE_TIME := "ExposureTime",
                PROP_GAIN := "Gain",
                PROP_OFFSET_X := "OffsetX",
                PROP_OFFSET_Y := "OffsetY",
                PROP_ACQUISITION_MODE := "AcquisitionMode",
                PROP_TRIGGER_MODE := "TriggerMode",
                PROP_ACQUISITION_FRAME_RATE := "AcquisitionFrameRate",
            ]
            for name in prop_names:
                try:
                    prop = pm.find(name)
                    if prop and prop.is_available:
                        pinfo = {"value": prop.value}
                        for attr in ("minimum", "maximum", "increment"):
                            if hasattr(prop, attr):
                                pinfo[attr] = getattr(prop, attr)
                        if isinstance(prop, PropEnumeration):
                            pinfo["options"] = [e.name for e in prop.entries]
                        pinfo["readonly"] = getattr(prop, "is_readonly", False)
                        info["properties"][name] = pinfo
                except Exception:
                    continue
            grabber.device_close()
        except Exception:
            # skip property gathering on error
            pass
        devices.append(info)
    return devices


def main():
    report = {
        "system": gather_system_info(),
        "library": gather_library_info(),
        "devices": gather_device_info(),
    }
    # write JSON report
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))
    print(f"Camera report written to: {REPORT_PATH}")


def exit_library():
    try:
        ic4.Library.exit()
    except Exception:
        pass


if __name__ == "__main__":
    main()
    exit_library()
