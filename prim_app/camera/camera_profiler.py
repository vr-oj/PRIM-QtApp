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
            msg = str(e).lower()
            if "already called" in msg:
                module_log.debug("IC4.Library.init() already called, continuing")
            else:
                module_log.error(f"Error initializing IC4 library: {e}")
                raise
        _initialized = True


def profile_camera() -> list:
    """
    Discover all IC4 cameras, returning [{'model': str, 'serial': str}, ...].
    """
    _ensure_initialized()
    devices = ic4.DeviceEnum.devices() or []
    cams = []
    for d in devices:
        model = getattr(d, "model_name", None) or getattr(d, "display_name", "Unknown")
        serial = getattr(d, "serial_number", "") or ""
        cams.append({"model": model, "serial": serial})
        module_log.debug(f"Found camera: {model} (SN: {serial})")
    if not cams:
        module_log.warning("No IC4 cameras found.")
    return cams


def get_camera_node_map(model: str, serial_pattern: str) -> dict:
    """
    Open the matching camera and return basic node "current" values.
    """
    _ensure_initialized()
    grabber = ic4.Grabber()
    try:
        devs = ic4.DeviceEnum.devices() or []
        dev = None
        # match by serial first, then by exact model
        for x in devs:
            sn = getattr(x, "serial_number", "") or ""
            md = getattr(x, "model_name", None) or getattr(x, "display_name", "")
            if sn and serial_pattern in sn:
                dev = x
                break
            if not sn and serial_pattern == md:
                dev = x
                break
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
                # try each getter until one succeeds
                try:
                    val = prop_map.get_value_int(pid)
                except Exception:
                    try:
                        val = prop_map.get_value_float(pid)
                    except Exception:
                        try:
                            val = prop_map.get_value_str(pid)
                        except Exception:
                            val = prop_map.get_value_bool(pid)
                nodemap[pid.name] = {"current": val}
            except Exception as exc:
                module_log.warning(f"Failed reading {pid.name}: {exc}")
        return nodemap
    finally:
        # close if open
        if getattr(grabber, "is_device_open", False):
            grabber.device_close()


def test_capture(model: str, serial_pattern: str, settings: dict) -> bool:
    """
    Apply settings to the camera, grab one frame, return True on success.
    """
    _ensure_initialized()
    grabber = ic4.Grabber()
    try:
        devs = ic4.DeviceEnum.devices() or []
        dev = next(
            (x for x in devs if serial_pattern in getattr(x, "serial_number", "")), None
        )
        if not dev:
            raise RuntimeError(f"Camera with serial '{serial_pattern}' not found.")
        grabber.device_open(dev)
        prop_map = grabber.device_property_map
        # apply each setting if PropId exists
        for name, val in settings.items():
            pid = getattr(ic4.PropId, name, None)
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
        if getattr(grabber, "is_acquisition_active", False):
            grabber.acquisition_stop()
            grabber.stream_stop()
        if getattr(grabber, "is_device_open", False):
            grabber.device_close()
