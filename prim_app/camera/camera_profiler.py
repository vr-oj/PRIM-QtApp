# prim_app/camera/camera_profiler.py
import logging
import imagingcontrol4 as ic4

module_log = logging.getLogger(__name__)  # Use __name__ for logger
_initialized_profiler = False  # Use a different flag name to avoid conflict if prim_app.py also has _initialized


def _ensure_profiler_initialized():
    global _initialized_profiler
    if not _initialized_profiler:
        try:
            # Library.init() should ideally be called only once per application run.
            # Rely on prim_app.py to have initialized it.
            # If this module is run standalone or if init status is uncertain,
            # it might be needed here, but can cause "already called" issues.
            # For now, assume it's initialized by the main app.
            # ic4.Library.init()
            # module_log.info("IC4 library initialized by camera_profiler (if not already by main app)")
            pass
        except RuntimeError as e:
            msg = str(e).lower()
            if "already called" in msg:
                module_log.debug(
                    "IC4.Library.init() already called (profiler), continuing"
                )
            else:
                module_log.error(f"Error initializing IC4 library in profiler: {e}")
                raise  # Re-raise if it's a different init error
        _initialized_profiler = True  # Mark as checked/attempted by profiler


def profile_camera() -> (
    list
):  # Renamed from profile_camera to avoid confusion if you have another one
    """
    Discover all IC4 cameras, returning [{'model': str, 'serial': str, 'unique_name': str}, ...].
    """
    _ensure_profiler_initialized()  # Ensures library is thought to be init by this module
    devices_info_list = ic4.DeviceEnum.devices() or []
    cameras_found = []
    for dev_info in devices_info_list:
        model = (
            dev_info.model_name if hasattr(dev_info, "model_name") else "Unknown Model"
        )
        serial = dev_info.serial if hasattr(dev_info, "serial") else ""
        unique_name = dev_info.unique_name if hasattr(dev_info, "unique_name") else ""
        cameras_found.append(
            {"model": model, "serial": serial, "unique_name": unique_name}
        )
        module_log.debug(
            f"Profiler found camera: {model} (SN: {serial}, Unique: {unique_name})"
        )
    if not cameras_found:
        module_log.warning("Profiler: No IC4 cameras found.")
    return cameras_found


def get_camera_node_map(
    model_name_filter: str, serial_or_unique_name_filter: str
) -> dict:
    """
    Open the matching camera and return basic node "current" values and ranges/options.
    Uses serial_or_unique_name_filter primarily, then model_name_filter as a weaker match.
    """
    _ensure_profiler_initialized()

    grabber = None  # Define grabber outside try to ensure it's in scope for finally
    try:
        all_devices = ic4.DeviceEnum.devices() or []
        target_device_info = None

        # Try to find by serial or unique name first
        if serial_or_unique_name_filter:
            for dev_info in all_devices:
                dev_serial = dev_info.serial if hasattr(dev_info, "serial") else ""
                dev_unique_name = (
                    dev_info.unique_name if hasattr(dev_info, "unique_name") else ""
                )
                if (
                    serial_or_unique_name_filter == dev_serial
                    or serial_or_unique_name_filter == dev_unique_name
                ):
                    target_device_info = dev_info
                    break

        # If not found by serial/unique, try by model name (less precise if multiple of same model)
        if not target_device_info and model_name_filter:
            for dev_info in all_devices:
                if model_name_filter == dev_info.model_name:
                    target_device_info = dev_info
                    module_log.warning(
                        f"Found by model name '{model_name_filter}' as serial/unique ID did not match or was not provided."
                    )
                    break

        if not target_device_info:
            raise RuntimeError(
                f"Camera matching model '{model_name_filter}' and/or identifier '{serial_or_unique_name_filter}' not found."
            )

        grabber = ic4.Grabber()
        grabber.device_open(target_device_info)
        prop_map = grabber.device_property_map

        nodemap_details = {}

        # Define properties of interest as strings (UPPER_SNAKE_CASE, matching ic4.PropId attribute names)
        properties_to_query = [
            "WIDTH",
            "HEIGHT",
            "PIXEL_FORMAT",
            "EXPOSURE_TIME",
            "EXPOSURE_AUTO",
            "GAIN",
            "ACQUISITION_FRAME_RATE",
            # Add other common properties the wizard might need to display/configure
        ]

        for prop_string_name in properties_to_query:
            prop_id_obj = getattr(
                ic4.PropId, prop_string_name, None
            )  # Get the actual PropId object
            if not prop_id_obj:
                module_log.warning(
                    f"PropId constant '{prop_string_name}' not found in ic4.PropId."
                )
                continue

            entry = {}
            try:
                # Get current value
                # Using a generic read_current like in SDKCameraThread might be better here
                current_val = None
                try:
                    current_val = prop_map.get_value_int(prop_id_obj)
                except ic4.IC4Exception:
                    try:
                        current_val = prop_map.get_value_float(prop_id_obj)
                    except ic4.IC4Exception:
                        try:
                            current_val = prop_map.get_value_str(prop_id_obj)
                        except ic4.IC4Exception:
                            try:
                                current_val = prop_map.get_value_bool(prop_id_obj)
                            except ic4.IC4Exception:
                                module_log.debug(
                                    f"Could not read current value for {prop_string_name}"
                                )
                if current_val is not None:
                    entry["current"] = current_val

                # Get Min/Max for Integer/Float types
                # Conceptual: Check property type first if API allows, e.g. prop_map.get_type(prop_id_obj)
                try:
                    entry["min"] = prop_map.get_min(prop_id_obj)
                except ic4.IC4Exception:
                    pass
                try:
                    entry["max"] = prop_map.get_max(prop_id_obj)
                except ic4.IC4Exception:
                    pass
                try:
                    entry["inc"] = prop_map.get_increment(prop_id_obj)  # If available
                except ic4.IC4Exception:
                    pass

                # Get Options for Enumeration types (like PixelFormat, ExposureAuto)
                # This requires knowing if it's an enum. The ic4 API might have a way to check property type.
                # For now, we can hardcode checks for known enum properties.
                if prop_string_name in [
                    "PIXEL_FORMAT",
                    "EXPOSURE_AUTO",
                ]:  # Example known enums
                    try:
                        enum_entries = prop_map.get_available_enumeration_entry_names(
                            prop_id_obj
                        )
                        entry["options"] = list(enum_entries)  # Convert tuple to list
                    except ic4.IC4Exception as e_enum:
                        module_log.debug(
                            f"Could not get enum options for {prop_string_name}: {e_enum}"
                        )

                # Add type information if possible (conceptual, depends on PyIC4 API)
                # try:
                #     prop_instance = prop_map.find_property(prop_string_name) # Or find by PropId object
                #     entry["type"] = str(prop_instance.type) # e.g. "IInteger", "IEnumeration"
                # except: pass

                if entry:  # If we got any info for this property
                    nodemap_details[prop_string_name] = entry  # Use string name as key

            except (
                Exception
            ) as exc_prop_read:  # Catch all for safety during individual property query
                module_log.warning(
                    f"Failed reading details for property '{prop_string_name}': {exc_prop_read}"
                )

        return nodemap_details
    finally:
        if grabber and grabber.is_device_open():
            grabber.device_close()
        module_log.debug("get_camera_node_map finished and cleaned up grabber.")


def test_capture(
    model_name_filter: str, serial_or_unique_name_filter: str, settings_to_apply: dict
) -> bool:
    """
    Apply settings to the camera, grab one frame, return True on success.
    """
    _ensure_profiler_initialized()
    grabber = None
    try:
        all_devices = ic4.DeviceEnum.devices() or []
        target_device_info = None
        if serial_or_unique_name_filter:  # Prioritize serial/unique name
            for dev_info in all_devices:
                dev_serial = dev_info.serial if hasattr(dev_info, "serial") else ""
                dev_unique_name = (
                    dev_info.unique_name if hasattr(dev_info, "unique_name") else ""
                )
                if (
                    serial_or_unique_name_filter == dev_serial
                    or serial_or_unique_name_filter == dev_unique_name
                ):
                    target_device_info = dev_info
                    break
        if not target_device_info and model_name_filter:  # Fallback to model name
            for dev_info in all_devices:
                if model_name_filter == dev_info.model_name:
                    target_device_info = dev_info
                    break
        if not target_device_info:
            raise RuntimeError(
                f"TestCapture: Camera matching '{serial_or_unique_name_filter or model_name_filter}' not found."
            )

        grabber = ic4.Grabber()
        grabber.device_open(target_device_info)
        prop_map = grabber.device_property_map

        # Apply settings: settings_to_apply keys are CamelCase from wizard
        for key_camel_case, val in settings_to_apply.items():
            # Convert CamelCase key to UPPER_SNAKE_CASE to find PropId object
            # This assumes wizard uses CamelCase keys matching what to_prop_name in SDKCameraThread expects
            prop_name_upper_snake = SDKCameraThread.to_prop_name(
                key_camel_case
            )  # Use to_prop_name from SDK thread
            prop_id_obj = getattr(ic4.PropId, prop_name_upper_snake, None)

            if prop_id_obj:
                try:
                    module_log.debug(
                        f"TestCapture: Setting {prop_name_upper_snake} to {val}"
                    )
                    if prop_name_upper_snake == "PIXEL_FORMAT" and isinstance(val, str):
                        pixel_format_member = getattr(ic4.PixelFormat, val, None)
                        if pixel_format_member:
                            prop_map.set_value(prop_id_obj, pixel_format_member)
                        else:
                            prop_map.set_value(prop_id_obj, val)  # Try string
                    elif prop_name_upper_snake == "EXPOSURE_AUTO" and isinstance(
                        val, str
                    ):
                        prop_map.set_value(prop_id_obj, val)
                    else:
                        prop_map.set_value(prop_id_obj, val)
                except Exception as se:
                    module_log.warning(
                        f"TestCapture: Could not set {prop_name_upper_snake} to {val}: {se}"
                    )
            else:
                module_log.warning(
                    f"TestCapture: PropId for '{prop_name_upper_snake}' (from '{key_camel_case}') not found."
                )

        sink = ic4.SnapSink()  # For a single frame
        grabber.stream_setup(
            sink
        )  # Default ACQUISITION_START often implied or not needed for SnapSink

        ok = False
        try:
            # SnapSink typically does not need acquisition_start explicitly
            # grabber.acquisition_start()
            buf = sink.snap_single(timeout_ms=2000)  # Snap single image with timeout
            if buf and buf.is_valid:  # Check if buffer is valid
                ok = True
                buf.release()
                module_log.info("TestCapture: Frame acquired successfully.")
            else:
                module_log.warning(
                    "TestCapture: snap_single returned invalid or no buffer."
                )
        except ic4.IC4Exception as be:
            module_log.error(f"TestCapture: snap_single error: {be} (Code: {be.code})")
        return ok
    finally:
        if grabber:
            if (
                hasattr(grabber, "is_acquisition_active")
                and grabber.is_acquisition_active()
            ):  # Check if attribute exists
                try:
                    grabber.acquisition_stop()
                except:
                    pass  # Best effort
            if grabber.is_device_open():
                grabber.device_close()
        module_log.debug("test_capture finished and cleaned up grabber.")
