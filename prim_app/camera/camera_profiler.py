# PRIM-QTAPP/prim_app/camera/camera_profiler.py
import imagingcontrol4 as ic4
import logging

module_log = logging.getLogger(__name__)  # Use a logger for this module


def _get_ic4_library_methods_interface():
    """
    Helper to determine the correct interface for IC4 Library methods like
    loadGenTLProducer and init, checking ic4.Library and ic4.Library._core.
    """
    # Check direct access on ic4.Library first (less likely given previous logs but good for robustness)
    if hasattr(ic4.Library, "loadGenTLProducer") and hasattr(ic4.Library, "init"):
        module_log.debug("Using ic4.Library directly for loadGenTLProducer and init.")
        return ic4.Library
    # Check access via ic4.Library._core
    elif (
        hasattr(ic4.Library, "_core")
        and hasattr(ic4.Library._core, "loadGenTLProducer")
        and hasattr(ic4.Library._core, "init")
    ):
        module_log.debug("Using ic4.Library._core for loadGenTLProducer and init.")
        return ic4.Library._core
    else:
        # Log details if no suitable interface found
        module_log.error(
            "Could not find a valid interface for loadGenTLProducer/init on ic4.Library or ic4.Library._core."
        )
        if hasattr(ic4.Library, "_core"):
            module_log.error(
                f"Attributes of ic4.Library._core: {dir(ic4.Library._core)}"
            )
        else:
            module_log.error("ic4.Library._core attribute not found.")
        module_log.error(
            f"Attributes of ic4.Library (instance of _LibraryProperties): {dir(ic4.Library)}"
        )
        raise AttributeError(
            "loadGenTLProducer or init method not found on expected ic4.Library interfaces."
        )


def profile_camera(cti_path: str) -> list:
    """
    Discover available cameras via the given GenTL producer (.cti).
    Returns a list of dicts: [{'model': str, 'serial': str}, ...]
    """
    module_log.info(f"Attempting to profile camera with CTI: {cti_path}")

    try:
        lib_interface = _get_ic4_library_methods_interface()
        module_log.info(f"Using IC4 interface: {lib_interface} for load/init.")
        lib_interface.loadGenTLProducer(cti_path)
        lib_interface.init()  # Initialize with the loaded CTI
        module_log.info(
            f"Successfully called loadGenTLProducer and init via determined interface."
        )
    except AttributeError as e:
        module_log.error(f"AttributeError during IC4 setup in profile_camera: {e}")
        raise  # Re-raise to be caught by the wizard and displayed
    except Exception as e:
        module_log.error(f"General Exception during IC4 setup in profile_camera: {e}")
        raise  # Re-raise

    # DeviceEnum.devices() should now use the correctly initialized library state
    devices = ic4.DeviceEnum.devices()
    result = []
    if not devices:
        module_log.warning(
            "No camera devices found after CTI load and init in profile_camera."
        )
    else:
        module_log.info(f"Found {len(devices)} device(s).")
        for dev in devices:
            model = getattr(dev, "model_name", "") or getattr(dev, "display_name", "")
            serial = getattr(dev, "serial_number", "")
            result.append({"model": model, "serial": serial})
            module_log.debug(f"Device details: Model='{model}', Serial='{serial}'")
    return result


def get_camera_node_map(cti_path: str, model: str, serial_pattern: str) -> dict:
    """
    Opens the selected camera and returns a mapping of node names to metadata.
    """
    module_log.info(f"Getting camera node map for CTI: {cti_path}, Model: {model}")
    try:
        lib_interface = _get_ic4_library_methods_interface()
        lib_interface.loadGenTLProducer(
            cti_path
        )  # Ensure CTI is loaded for this operation
        lib_interface.init()
        module_log.info(f"IC4 interface prepared for get_camera_node_map.")
    except AttributeError as e:
        module_log.error(f"AttributeError during IC4 setup in get_camera_node_map: {e}")
        raise
    except Exception as e:
        module_log.error(
            f"General Exception during IC4 setup in get_camera_node_map: {e}"
        )
        raise

    grabber = ic4.Grabber()
    devices = ic4.DeviceEnum.devices()  # Uses current library state
    if not devices:
        raise RuntimeError(f"No devices found for nodemap retrieval (CTI: {cti_path}).")

    dev_info = next(
        (d for d in devices if serial_pattern in getattr(d, "serial_number", "")), None
    )
    if not dev_info:
        raise RuntimeError(
            f"Camera matching SN pattern '{serial_pattern}' not found for nodemap."
        )

    try:
        grabber.device_open(dev_info)
        module_log.info(f"Device '{model}' opened successfully for nodemap.")
        nodemap = {}
        prop_map = grabber.device_property_map
        # Inspect common nodes (as in your original code)
        for pid_name in [
            "EXPOSURE_TIME",
            "EXPOSURE_AUTO",
            "PIXEL_FORMAT",
            "WIDTH",
            "HEIGHT",
        ]:
            try:
                pid = getattr(ic4.PropId, pid_name, None)
                if pid is None:
                    module_log.warning(
                        f"PropId for '{pid_name}' not found in ic4.PropId."
                    )
                    continue

                current = prop_map.get_value(pid)
                info = {
                    "type": pid.name,
                    "current": current,
                }  # Use pid.name for consistency
                try:
                    info["min"] = prop_map.get_min(pid)
                except Exception:
                    pass
                try:
                    info["max"] = prop_map.get_max(pid)
                except Exception:
                    pass
                try:
                    info["options"] = prop_map.get_enum_entries(pid)
                except Exception:
                    pass
                nodemap[pid.name] = info  # Store by actual PropId name
            except Exception as prop_e:
                module_log.warning(f"Could not get property '{pid_name}': {prop_e}")
                continue
    finally:
        if grabber.is_device_open():
            grabber.device_close()
    return nodemap


def test_capture(
    cti_path: str, model: str, serial_pattern: str, settings: dict
) -> bool:
    """
    Applies settings, grabs a frame, returns True if successful.
    """
    module_log.info(f"Testing capture for CTI: {cti_path}, Model: {model}")
    try:
        lib_interface = _get_ic4_library_methods_interface()
        lib_interface.loadGenTLProducer(cti_path)  # Ensure CTI is loaded
        lib_interface.init()
        module_log.info(f"IC4 interface prepared for test_capture.")
    except AttributeError as e:
        module_log.error(f"AttributeError during IC4 setup in test_capture: {e}")
        raise
    except Exception as e:
        module_log.error(f"General Exception during IC4 setup in test_capture: {e}")
        raise

    grabber = ic4.Grabber()
    devices = ic4.DeviceEnum.devices()
    if not devices:
        raise RuntimeError(f"No devices found for test capture (CTI: {cti_path}).")

    dev_info = next(
        (d for d in devices if serial_pattern in getattr(d, "serial_number", "")), None
    )
    if not dev_info:
        raise RuntimeError(
            f"Camera matching SN pattern '{serial_pattern}' not found for test capture."
        )

    ok = False
    try:
        grabber.device_open(dev_info)
        module_log.info(f"Device '{model}' opened for test capture.")
        prop_map = grabber.device_property_map
        for name, value in settings.items():
            try:
                # Attempt to match name with PropId enum members, case-insensitively or with common variations
                pid = None
                if hasattr(ic4.PropId, name.upper()):
                    pid = getattr(ic4.PropId, name.upper())
                elif hasattr(ic4.PropId, name):  # Exact match
                    pid = getattr(ic4.PropId, name)

                if pid:
                    prop_map.set_value(pid, value)
                    module_log.debug(f"Set property {pid.name} to {value}.")
                else:
                    module_log.warning(
                        f"Property name '{name}' not found in ic4.PropId during test_capture settings."
                    )
            except Exception as set_prop_e:
                module_log.warning(
                    f"Could not set property {name} to {value}: {set_prop_e}"
                )
                pass

        sink = ic4.QueueSink()
        grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)
        grabber.acquisition_start()

        try:
            buf = sink.pop_output_buffer(2000)  # Timeout in ms
            if buf:
                ok = True
                module_log.info("Test frame acquired successfully.")
                buf.release()
            else:
                module_log.warning(
                    "Test capture: pop_output_buffer timed out or returned no buffer."
                )
        except Exception as pop_e:
            module_log.error(
                f"Exception during pop_output_buffer in test_capture: {pop_e}"
            )
            ok = False

    finally:
        if grabber.is_streaming():
            grabber.acquisition_stop()
            grabber.stream_stop()
        if grabber.is_device_open():
            grabber.device_close()
        module_log.info(f"Test capture finished. Success: {ok}")
    return ok
