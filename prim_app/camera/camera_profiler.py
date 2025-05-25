# PRIM-QTAPP/prim_app/camera/camera_profiler.py
import imagingcontrol4 as ic4
import logging  # Add this

module_log = logging.getLogger(__name__)  # Use a logger for debug messages


def profile_camera(cti_path: str) -> list:
    """
    Discover available cameras via the given GenTL producer (.cti).
    Returns a list of dicts: [{'model': str, 'serial': str}, ...]
    """
    module_log.info(f"Attempting to profile camera with CTI: {cti_path}")
    module_log.info(f"Type of 'ic4' in camera_profiler: {type(ic4)}")
    module_log.info(f"Type of 'ic4.Library' in camera_profiler: {type(ic4.Library)}")
    module_log.info(
        f"Attributes of 'ic4.Library' in camera_profiler: {dir(ic4.Library)}"
    )

    # The line below is where the error occurs
    ic4.Library.loadGenTLProducer(cti_path)
    ic4.Library.init()  # This should be safe to call even if already initialized

    # Enumerate devices
    devices = ic4.DeviceEnum.devices()
    result = []
    for dev in devices:
        model = getattr(dev, "model_name", "") or getattr(dev, "display_name", "")
        serial = getattr(dev, "serial_number", "")
        result.append({"model": model, "serial": serial})
    return result


def get_camera_node_map(cti_path: str, model: str, serial_pattern: str) -> dict:
    """
    Opens the selected camera and returns a mapping of node names to metadata:
    e.g., {'ExposureTime': {'type': 'IFloat', 'current': 20.0, 'min': 1.0, 'max': 60000.0}, ...}
    """
    # Ensure CTI loaded
    ic4.Library.loadGenTLProducer(cti_path)
    ic4.Library.init()

    grabber = ic4.Grabber()
    devices = ic4.DeviceEnum.devices()
    # Find matching device
    dev_info = next(
        (d for d in devices if serial_pattern in getattr(d, "serial_number", "")), None
    )
    if not dev_info:
        raise RuntimeError(f"Camera matching '{serial_pattern}' not found")
    grabber.device_open(dev_info)

    nodemap = {}
    prop_map = grabber.device_property_map
    # Inspect a few common nodes
    for pid in [
        ic4.PropId.EXPOSURE_TIME,
        ic4.PropId.EXPOSURE_AUTO,
        ic4.PropId.PIXEL_FORMAT,
        ic4.PropId.WIDTH,
        ic4.PropId.HEIGHT,
    ]:
        try:
            current = prop_map.get_value(pid)
            info = {
                "type": pid.name,  # placeholder: using name as type
                "current": current,
            }
            # Try to fetch ranges if available
            try:
                info["min"] = prop_map.get_min(pid)
                info["max"] = prop_map.get_max(pid)
            except Exception:
                pass
            # For enumerations, get choices
            try:
                info["options"] = prop_map.get_enum_entries(pid)
            except Exception:
                pass
            nodemap[pid.name] = info
        except Exception:
            continue
    grabber.device_close()
    return nodemap


def test_capture(
    cti_path: str, model: str, serial_pattern: str, settings: dict
) -> bool:
    """
    Applies the given settings to the camera, grabs a single frame, and returns True if successful.
    """
    # Ensure CTI loaded
    ic4.Library.loadGenTLProducer(cti_path)
    ic4.Library.init()

    grabber = ic4.Grabber()
    devices = ic4.DeviceEnum.devices()
    dev_info = next(
        (d for d in devices if serial_pattern in getattr(d, "serial_number", "")), None
    )
    if not dev_info:
        raise RuntimeError(f"Camera matching '{serial_pattern}' not found")
    grabber.device_open(dev_info)

    # Apply settings
    prop_map = grabber.device_property_map
    for name, value in settings.items():
        try:
            pid = getattr(ic4.PropId, name.upper())
            prop_map.set_value(pid, value)
        except Exception:
            pass

    # Setup streaming and grab one frame
    sink = ic4.QueueSink()
    grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)
    grabber.acquisition_start()

    try:
        buf = sink.pop_output_buffer(2000)
        ok = buf is not None
    except Exception:
        ok = False
    finally:
        grabber.acquisition_stop()
        grabber.stream_stop()
        grabber.device_close()

    return bool(ok)
