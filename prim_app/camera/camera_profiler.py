# prim_app/camera/camera_profiler.py

import logging
import imagingcontrol4 as ic4

module_log = logging.getLogger(__name__)


def profile_camera() -> list:
    """
    Initialize the IC4 library and discover available cameras.
    Returns a list of dicts: [{'model': str, 'serial': str}, ...]
    """
    module_log.info("Initializing IC4 and enumerating cameras...")
    ic4.Library.init()
    devices = ic4.DeviceEnum.devices()
    result = []
    if not devices:
        module_log.warning("No IC4 cameras found.")
    for dev in devices:
        model = getattr(dev, "model_name", "") or getattr(dev, "display_name", "")
        serial = getattr(dev, "serial_number", "")
        result.append({"model": model, "serial": serial})
        module_log.debug(f"Found camera: {model} (SN: {serial})")
    return result


def get_camera_node_map(model: str, serial_pattern: str) -> dict:
    """
    Opens the selected camera and returns a mapping of node names to metadata.
    """
    module_log.info(f"Building node map for {model} / {serial_pattern}")
    ic4.Library.init()
    grabber = ic4.Grabber()
    devices = ic4.DeviceEnum.devices()
    dev_info = next((d for d in devices if serial_pattern in d.serial_number), None)
    if not dev_info:
        raise RuntimeError(f"Camera SN '{serial_pattern}' not found.")
    grabber.device_open(dev_info)

    nodemap = {}
    prop_map = grabber.device_property_map
    for pid in (
        ic4.PropId.EXPOSURE_TIME,
        ic4.PropId.EXPOSURE_AUTO,
        ic4.PropId.PIXEL_FORMAT,
        ic4.PropId.WIDTH,
        ic4.PropId.HEIGHT,
    ):
        try:
            current = prop_map.get_value(pid)
            info = {"current": current}
            try:
                info["min"] = prop_map.get_min(pid)
            except:
                pass
            try:
                info["max"] = prop_map.get_max(pid)
            except:
                pass
            try:
                info["options"] = prop_map.get_enum_entries(pid)
            except:
                pass
            nodemap[pid.name] = info
        except Exception as e:
            module_log.warning(f"Couldn’t read {pid.name}: {e}")
    grabber.device_close()
    return nodemap


def test_capture(model: str, serial_pattern: str, settings: dict) -> bool:
    """
    Applies settings, grabs one frame, and returns True if successful.
    """
    module_log.info(f"Test capture for {model} / {serial_pattern}")
    ic4.Library.init()
    grabber = ic4.Grabber()
    dev = next(
        (d for d in ic4.DeviceEnum.devices() if serial_pattern in d.serial_number), None
    )
    if not dev:
        raise RuntimeError(f"No camera matching {serial_pattern}")

    grabber.device_open(dev)
    prop_map = grabber.device_property_map
    for name, val in settings.items():
        pid = getattr(ic4.PropId, name.upper(), None)
        if pid:
            try:
                prop_map.set_value(pid, val)
            except Exception:
                module_log.warning(f"Failed to set {pid.name} to {val}")

    sink = ic4.QueueSink()
    grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)
    grabber.acquisition_start()
    ok = False
    try:
        buf = sink.pop_output_buffer(2000)
        if buf:
            ok = True
            buf.release()
    except Exception as e:
        module_log.error(f"pop_output_buffer failed: {e}")
    finally:
        if grabber.is_acquisition_active:
            grabber.acquisition_stop()
            grabber.stream_stop()
        grabber.device_close()

    module_log.info(f"Test capture result: {ok}")
    return ok
