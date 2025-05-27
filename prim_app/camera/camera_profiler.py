# prim_app/camera/camera_profiler.py
import logging
import imagingcontrol4 as ic4

# from threads.sdk_camera_thread import to_prop_name # Not strictly needed if wizard provides CamelCase keys

module_log = logging.getLogger(__name__)
_initialized_profiler = False

# It's better if SDKCameraThread's to_prop_name is in a utils file if shared
# For now, if wizard gives CamelCase keys, test_capture will use them.
# get_camera_node_map will use UPPER_SNAKE_CASE strings for querying.


def _ensure_profiler_initialized():  # Keep this as is
    global _initialized_profiler
    if not _initialized_profiler:
        try:
            pass
        except RuntimeError as e:
            msg = str(e).lower()
            if "already called" in msg:
                module_log.debug(
                    "IC4.Library.init() already called (profiler), continuing"
                )
            else:
                module_log.error(f"Error initializing IC4 library in profiler: {e}")
                raise
        _initialized_profiler = True


def profile_camera_devices() -> list:  # Renamed to avoid conflict
    _ensure_profiler_initialized()
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
    _ensure_profiler_initialized()
    grabber = None
    try:
        all_devices = ic4.DeviceEnum.devices() or []
        target_device_info = None
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
        if not target_device_info and model_name_filter:
            for dev_info in all_devices:
                if model_name_filter == dev_info.model_name:
                    target_device_info = dev_info
                    module_log.warning(f"Found by model name '{model_name_filter}'.")
                    break
        if not target_device_info:
            raise RuntimeError(
                f"Camera matching '{serial_or_unique_name_filter or model_name_filter}' not found."
            )

        grabber = ic4.Grabber()
        grabber.device_open(target_device_info)
        prop_map = grabber.device_property_map
        nodemap_details = {}

        properties_to_query = [  # UPPER_SNAKE_CASE string names
            "WIDTH",
            "HEIGHT",
            "PIXEL_FORMAT",
            "EXPOSURE_TIME",
            "EXPOSURE_AUTO",
            "GAIN",
            "ACQUISITION_FRAME_RATE",
        ]

        for prop_string_name in properties_to_query:
            entry = {}
            try:
                prop_item = prop_map.find(prop_string_name)  # Find by string name
                if prop_item is None:
                    module_log.warning(
                        f"Property '{prop_string_name}' not found in profiler via pm.find()."
                    )
                    continue

                # Get current value
                # Some properties might not have .value directly, or it might not be the best way
                # A robust read_current function would be better here too.
                try:
                    if prop_item.type == ic4.PropertyType.INTEGER:
                        entry["current"] = prop_item.value  # Assuming .value gives int
                    elif prop_item.type == ic4.PropertyType.FLOAT:
                        entry["current"] = (
                            prop_item.value
                        )  # Assuming .value gives float
                    elif prop_item.type == ic4.PropertyType.BOOLEAN:
                        entry["current"] = prop_item.value  # Assuming .value gives bool
                    elif prop_item.type == ic4.PropertyType.ENUMERATION:
                        entry["current"] = (
                            prop_item.value
                        )  # This is often the string value for enums
                    elif prop_item.type == ic4.PropertyType.STRING:
                        entry["current"] = prop_item.value
                    else:
                        entry["current"] = str(
                            prop_item.value
                        )  # Fallback to string representation
                except Exception as e_val:
                    module_log.debug(
                        f"Could not read current value for {prop_string_name} via prop_item.value: {e_val}"
                    )

                if (
                    prop_item.type == ic4.PropertyType.INTEGER
                    or prop_item.type == ic4.PropertyType.FLOAT
                ):
                    if hasattr(prop_item, "min"):
                        entry["min"] = prop_item.min
                    if hasattr(prop_item, "max"):
                        entry["max"] = prop_item.max
                    if hasattr(prop_item, "increment"):
                        entry["inc"] = prop_item.increment

                if prop_item.type == ic4.PropertyType.ENUMERATION:
                    if hasattr(prop_item, "available_enumeration_names"):
                        entry["options"] = list(prop_item.available_enumeration_names)

                # Storing the GenICam type string (e.g. "IInteger", "IEnumeration")
                # The wizard's AdvancedSettingsPage uses this 'type' key.
                # The actual PropertyType enum member might be more like ic4.PropertyType.INTEGER.
                # We need to map ic4.PropertyType to the strings wizard expects, or change wizard.
                # For simplicity, let's map some common ones.
                type_mapping = {
                    ic4.PropertyType.INTEGER: "IInteger",
                    ic4.PropertyType.FLOAT: "IFloat",
                    ic4.PropertyType.ENUMERATION: "IEnumeration",
                    ic4.PropertyType.BOOLEAN: "IBoolean",
                    ic4.PropertyType.COMMAND: "ICommand",  # Wizard doesn't handle command, but for completeness
                    ic4.PropertyType.STRING: "IString",  # Wizard doesn't handle string, but for completeness
                }
                entry["type"] = type_mapping.get(prop_item.type, str(prop_item.type))

                if entry:
                    nodemap_details[prop_string_name] = entry
            except Exception as exc_prop_read:
                module_log.warning(
                    f"Failed reading details for property '{prop_string_name}' in profiler: {exc_prop_read}"
                )

        return nodemap_details
    finally:
        if grabber and grabber.is_device_open:  # Check property, not method
            grabber.device_close()
        module_log.debug(
            "get_camera_node_map (profiler) finished and cleaned up grabber."
        )


def test_capture(
    model_name_filter: str, serial_or_unique_name_filter: str, settings_to_apply: dict
) -> bool:
    _ensure_profiler_initialized()
    grabber = None
    try:
        all_devices = ic4.DeviceEnum.devices() or []
        target_device_info = None
        # Device matching logic (same as in get_camera_node_map)
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
        if not target_device_info and model_name_filter:
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
            # Convert CamelCase key to UPPER_SNAKE_CASE to find PropId object or use as string name
            prop_name_upper_snake = to_prop_name(
                key_camel_case
            )  # Using to_prop_name from SDKCameraThread (needs import or move)

            # Use the string name for set_value, assuming it's accepted or PropId object from map if available
            # For simplicity, let's assume set_value can take string names if PropId obj isn't easily available here.
            # A more robust way would be to use the same _propid_map logic as SDKCameraThread.
            target_for_set_value = prop_name_upper_snake

            try:
                module_log.debug(
                    f"TestCapture: Setting {target_for_set_value} to {val}"
                )
                if prop_name_upper_snake == "PIXEL_FORMAT" and isinstance(val, str):
                    pixel_format_member = getattr(ic4.PixelFormat, val, None)
                    if pixel_format_member:
                        prop_map.set_value(target_for_set_value, pixel_format_member)
                    else:
                        prop_map.set_value(target_for_set_value, val)
                elif prop_name_upper_snake == "EXPOSURE_AUTO" and isinstance(val, str):
                    prop_map.set_value(target_for_set_value, val)
                else:
                    prop_map.set_value(target_for_set_value, val)
            except Exception as se:
                module_log.warning(
                    f"TestCapture: Could not set {target_for_set_value} to {val}: {se}"
                )

        sink = ic4.SnapSink()
        grabber.stream_setup(sink)
        ok = False
        try:
            buf = sink.snap_single(timeout_ms=2000)
            if buf and buf.is_valid:
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
                and grabber.is_acquisition_active
            ):  # property
                try:
                    grabber.acquisition_stop()
                except:
                    pass
            if grabber.is_device_open:  # property
                grabber.device_close()
        module_log.debug("test_capture finished and cleaned up grabber.")
