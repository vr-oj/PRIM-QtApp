# prim_app/camera/camera_profiler.py
import logging
import imagingcontrol4 as ic4
from utils.utils import to_prop_name  # Assuming to_prop_name is in utils.utils

module_log = logging.getLogger(__name__)
_initialized_profiler = False


def _ensure_profiler_initialized():
    global _initialized_profiler
    if not _initialized_profiler:
        # Assuming main app (prim_app.py) handles ic4.Library.init()
        _initialized_profiler = True


def profile_camera_devices() -> list:
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
        # Device matching logic (same as in SDKCameraThread)
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
                    module_log.warning(
                        f"Profiler: Found by model name '{model_name_filter}'."
                    )
                    break
        if not target_device_info:
            raise RuntimeError(
                f"Profiler: Camera matching '{serial_or_unique_name_filter or model_name_filter}' not found."
            )

        grabber = ic4.Grabber()
        grabber.device_open(target_device_info)
        prop_map = grabber.device_property_map
        nodemap_details = {}

        # Use CamelCase names as these are standard GenICam feature names
        # and what pm.find() will expect as string arguments.
        properties_to_query_camel_case = [
            "Width",
            "Height",
            "PixelFormat",
            "ExposureTime",
            "ExposureAuto",
            "Gain",
            "AcquisitionFrameRate",
            "OffsetX",
            "OffsetY",
            "TriggerMode",  # Added a few more common ones
        ]

        for feature_name_camel_case in properties_to_query_camel_case:
            entry = {}
            try:
                prop_item = prop_map.find(feature_name_camel_case)
                if prop_item is None:
                    module_log.debug(
                        f"Profiler: Feature '{feature_name_camel_case}' not found in PropertyMap."
                    )
                    continue

                # Get current value
                entry["current"] = (
                    prop_item.value
                )  # Assuming .value gives the appropriately typed value

                # Get Min/Max/Increment for relevant types
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

                type_mapping = {
                    ic4.PropertyType.INTEGER: "IInteger",
                    ic4.PropertyType.FLOAT: "IFloat",
                    ic4.PropertyType.ENUMERATION: "IEnumeration",
                    ic4.PropertyType.BOOLEAN: "IBoolean",
                    ic4.PropertyType.COMMAND: "ICommand",
                    ic4.PropertyType.STRING: "IString",
                }
                entry["type"] = type_mapping.get(prop_item.type, str(prop_item.type))
                entry["readonly"] = (
                    prop_item.is_readonly if hasattr(prop_item, "is_readonly") else True
                )

                if entry:  # Store with CamelCase key, as wizard pages might expect this
                    nodemap_details[feature_name_camel_case] = entry
            except Exception as exc_prop_read:
                module_log.warning(
                    f"Profiler: Failed reading details for property '{feature_name_camel_case}': {exc_prop_read}"
                )

        module_log.debug(f"Profiler: Node map created: {nodemap_details.keys()}")
        return nodemap_details
    finally:
        if grabber and hasattr(grabber, "is_device_open") and grabber.is_device_open:
            grabber.device_close()
        module_log.debug(
            "Profiler: get_camera_node_map finished and cleaned up grabber."
        )


def test_capture(
    model_name_filter: str, serial_or_unique_name_filter: str, settings_to_apply: dict
) -> bool:
    # settings_to_apply keys are expected to be CamelCase from the wizard
    _ensure_profiler_initialized()
    grabber = None
    try:
        all_devices = ic4.DeviceEnum.devices() or []
        target_device_info = None
        # Device matching logic (same as above)
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

        for key_camel_case, val in settings_to_apply.items():
            try:
                # Attempt to set using the CamelCase name directly if set_value supports it,
                # or find the PropId object if needed.
                # For test_capture, using the string name directly with set_value is simpler if it works.
                # The SDKCameraThread's apply_node_settings is more robust by using PropId objects.

                # Get PropId object for more robust setting
                prop_id_obj = getattr(ic4.PropId, to_prop_name(key_camel_case), None)
                if not prop_id_obj:
                    module_log.warning(
                        f"TestCapture: No PropId object for '{key_camel_case}'. Skipping set for this property."
                    )
                    continue

                module_log.debug(
                    f"TestCapture: Setting {key_camel_case} (using PropId obj) to {val}"
                )
                if key_camel_case == "PixelFormat" and isinstance(
                    val, str
                ):  # Special handling
                    pixel_format_member = getattr(ic4.PixelFormat, val, None)
                    if pixel_format_member:
                        prop_map.set_value(prop_id_obj, pixel_format_member)
                    else:
                        prop_map.set_value(prop_id_obj, val)
                elif key_camel_case == "ExposureAuto" and isinstance(val, str):
                    prop_map.set_value(prop_id_obj, val)
                else:
                    prop_map.set_value(prop_id_obj, val)  # Use PropId object
            except Exception as se:
                module_log.warning(
                    f"TestCapture: Could not set {key_camel_case} to {val}: {se}"
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
            ):
                try:
                    grabber.acquisition_stop()
                except:
                    pass
            if hasattr(grabber, "is_device_open") and grabber.is_device_open:
                grabber.device_close()
        module_log.debug("test_capture finished and cleaned up grabber.")
