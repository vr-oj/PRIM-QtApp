# prim_app/camera/camera_profiler.py
import logging
import imagingcontrol4 as ic4

module_log = logging.getLogger(__name__)

_initialized = False


def _ensure_initialized():
    global _initialized
    if not _initialized:
        try:
            ic4.Library.init()
            module_log.info("IC4 library initialized")
        except RuntimeError as e:
            if "already called" in str(e).lower():
                module_log.debug("IC4.Library.init() was already called, continuing")
            else:
                module_log.error(f"Error initializing IC4 library: {e}")
                raise
        _initialized = True


def profile_camera() -> list:
    """
    Initialize the IC4 library (once) and discover available cameras.
    Returns a list of dicts: [{'model': str, 'serial': str}, ...]
    """
    _ensure_initialized()
    devices = ic4.DeviceEnum.devices()
    cams = []
    if not devices:
        module_log.warning("No IC4 cameras found.")
    for d in devices:
        model = getattr(d, "model_name", None) or getattr(d, "display_name", "Unknown")
        serial = getattr(d, "serial_number", "")
        cams.append({"model": model, "serial": serial})
        module_log.debug(f"Found camera: {model} (SN: {serial})")
    return cams


def get_camera_node_map(model: str, serial_pattern: str) -> dict:
    """
    Opens the selected camera and returns a mapping of key PropId names to metadata
    including only the current value.  Limits and options omitted for simplicity.
    """
    _ensure_initialized()
    grabber = ic4.Grabber()
    try:
        devs = ic4.DeviceEnum.devices()
        dev = next(
            (x for x in devs if serial_pattern in getattr(x, "serial_number", "")), None
        )
        if not dev:
            raise RuntimeError(f"Camera with serial '{serial_pattern}' not found.")
        grabber.device_open(dev)
        prop_map = grabber.device_property_map
        nodemap = {}
        for pid in (
            ic4.PropId.EXPOSURE_TIME,
            ic4.PropId.EXPOSURE_AUTO,
            ic4.PropId.PIXEL_FORMAT,
            ic4.PropId.WIDTH,
            ic4.PropId.HEIGHT,
        ):
            try:
                # Attempt different typed getters
                try:
                    val = prop_map.get_value_int(pid)
                except Exception:
                    try:
                        val = prop_map.get_value_float(pid)
                    except Exception:
                        try:
                            val = prop_map.get_value_str(pid)
                        except Exception:
                            try:
                                val = prop_map.get_value_bool(pid)
                            except Exception as e:
                                module_log.warning(f"Could not read {pid.name}: {e}")
                                continue
                nodemap[pid.name] = {"current": val}
            except Exception as exc:
                module_log.warning(f"Failed reading property {pid.name}: {exc}")
        return nodemap
    finally:
        if hasattr(grabber, "is_device_open") and grabber.is_device_open():
            grabber.device_close()


def test_capture(model: str, serial_pattern: str, settings: dict) -> bool:
    """
    Applies settings, grabs one frame, and returns True if successful.
    """
    _ensure_initialized()
    grabber = ic4.Grabber()
    try:
        devs = ic4.DeviceEnum.devices()
        dev = next(
            (x for x in devs if serial_pattern in getattr(x, "serial_number", "")), None
        )
        if not dev:
            raise RuntimeError(f"Camera with serial '{serial_pattern}' not found.")
        grabber.device_open(dev)
        prop_map = grabber.device_property_map
        # Apply settings
        for name, val in settings.items():
            pid = getattr(ic4.PropId, name.upper(), None)
            if pid:
                try:
                    prop_map.set_value(pid, val)
                except Exception as se:
                    module_log.warning(f"Could not set {name}: {se}")
        sink = ic4.QueueSink()
        grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)
        grabber.acquisition_start()
        ok = False
        try:
            buf = sink.pop_output_buffer(2000)
            if buf:
                ok = True
                buf.release()
        except Exception as be:
            module_log.error(f"pop_output_buffer error: {be}")
        return ok
    finally:
        if hasattr(grabber, "is_acquisition_active") and grabber.is_acquisition_active:
            grabber.acquisition_stop()
            grabber.stream_stop()
        if hasattr(grabber, "is_device_open") and grabber.is_device_open():
            grabber.device_close()
