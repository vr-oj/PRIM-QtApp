import logging
import sys
import platform
import json
import imagingcontrol4 as ic4
from imagingcontrol4.properties import PropInteger, PropFloat, PropEnumeration

# Set up logging
glogging = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def gather_system_info():
    return {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "architecture": platform.machine(),
    }


def gather_library_info():
    try:
        # Library version from imagingcontrol4
        lib_ver = ic4.Library.get_version()
    except Exception:
        lib_ver = None
    return {"imagingcontrol4_version": lib_ver}


def gather_devices_info():
    devices = []
    for dev in ic4.DeviceEnum.devices():
        di = {
            "model_name": dev.model_name,
            "serial": getattr(dev, "serial", None),
            "version": getattr(dev, "version", None),
        }
        try:
            # Open device to read properties
            grabber = ic4.Grabber()
            grabber.device_open(dev)
            pm = grabber.device_property_map
            # Determine available property names
            if hasattr(pm, "property_names"):
                names = pm.property_names
            elif hasattr(pm, "names"):
                names = pm.names
            else:
                try:
                    names = list(pm)
                except Exception:
                    names = []

            props = {}
            for name in names:
                try:
                    p = pm.find(name)
                    val = p.value
                    info = {"value": val}
                    if isinstance(p, PropInteger) or isinstance(p, PropFloat):
                        info.update(min=p.minimum, max=p.maximum, inc=p.increment)
                    elif isinstance(p, PropEnumeration):
                        info.update(options=[e.name for e in p.entries])
                    props[name] = info
                except Exception:
                    logging.debug(f"Failed to read property {name}")
            di["properties"] = props
            # Close device
            if getattr(grabber, "is_streaming", False):
                grabber.stream_stop()
            if getattr(grabber, "is_device_open", False):
                grabber.device_close()
        except Exception as e:
            logging.exception(f"Error gathering info for device {dev}")
        devices.append(di)
    return devices


def main():
    # Initialize IC4 library
    try:
        ic4.Library.init()
    except Exception as e:
        logging.warning(f"Library.init() failed: {e}")

    report = {
        "system": gather_system_info(),
        "library": gather_library_info(),
        "devices": gather_devices_info(),
    }

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
