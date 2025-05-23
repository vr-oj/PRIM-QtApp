import os
import platform
import glob
import time
from harvesters.core import Harvester
import numpy as np
import imageio

# --- Configuration ---
# Directly specified path for your test environment
YOUR_SPECIFIC_GENTL_PATH = r"C:\Program Files\The Imaging Source Europe GmbH\IC4 GenTL Driver for USB3Vision Devices 1.4\bin\ic4-gentl-u3v_x64.cti"

TARGET_SERIAL_NUMBER = None  # Or "YOUR_CAMERA_SERIAL_NUMBER"
OUTPUT_IMAGE_FILENAME = "captured_image.png"

# --- Camera Specific Configurations (ensure these are accurate) ---
# DMK 33UP5000
DMK_33UP5000_MODEL_STR = "33UP5000"
DMK_33UP5000_WIDTH = 2592  # [cite: 9, 62]
DMK_33UP5000_HEIGHT = 2048  # [cite: 9, 65]
DMK_33UP5000_PIXEL_FORMAT = (
    "Mono8"  # [cite: 9, 46] # For DMK 33UP5000, options: 'Mono8', 'Mono10p'
)

# DMK 33UX250
DMK_33UX250_MODEL_STR = "33UX250"
DMK_33UX250_WIDTH = 2448  # [cite: 268, 323]
DMK_33UX250_HEIGHT = 2048  # [cite: 268, 326]
DMK_33UX250_PIXEL_FORMAT = (
    "Mono8"  # [cite: 268, 307] # For DMK 33UX250, options: 'Mono8', 'Mono16'
)


def find_gentl_producer_path(specific_test_path=None):
    """
    Tries to find The Imaging Source GenTL producer (.cti file).
    Starts with the specific_test_path if provided.
    Returns the path to the .cti file if found, otherwise None.
    """
    if specific_test_path and os.path.isfile(specific_test_path):
        print(f"Using specific test GenTL producer path: {specific_test_path}")
        return specific_test_path
    elif specific_test_path:
        print(
            f"Warning: Specific test path not found: {specific_test_path}. Proceeding with other detection methods."
        )

    system = platform.system()
    architecture = platform.architecture()[0]
    env_var_name = (
        "GENICAM_GENTL64_PATH" if architecture == "64bit" else "GENICAM_GENTL32_PATH"
    )
    env_var = os.environ.get(env_var_name)

    if env_var:
        potential_cti_files = []
        for path_entry in env_var.split(os.pathsep):
            if os.path.isfile(path_entry) and path_entry.endswith(".cti"):
                potential_cti_files.append(path_entry)
            elif os.path.isdir(path_entry):
                potential_cti_files.extend(glob.glob(os.path.join(path_entry, "*.cti")))
        for cti_file in potential_cti_files:
            if (
                "tis" in cti_file.lower()
                or "theimagingsource" in cti_file.lower()
                or "ic4" in cti_file.lower()
            ):
                print(
                    f"Found GenTL producer via environment variable '{env_var_name}': {cti_file}"
                )
                return cti_file
        if potential_cti_files:
            print(
                f"Found a GenTL producer via environment variable '{env_var_name}' (generic): {potential_cti_files[0]}"
            )
            return potential_cti_files[0]

    search_paths = []
    if system == "Windows":
        if specific_test_path:
            search_paths.append(os.path.dirname(specific_test_path))
        base_paths = [
            os.environ.get("ProgramFiles", "C:\\Program Files"),
            os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
        ]
        for bp in base_paths:
            search_paths.append(
                os.path.join(
                    bp,
                    "The Imaging Source Europe GmbH",
                    "IC4 GenTL Driver for USB3Vision Devices 1.4",
                    "bin",
                )
            )
            search_paths.append(
                os.path.join(bp, "The Imaging Source", "Drivers", "gentl")
            )
    elif system == "Linux":
        search_paths.append("/opt/theimagingsource/tiscamera/genicam/gentl")
        search_paths.append("/opt/tis/lib/genicam/gentl")

    for path in search_paths:
        if os.path.isdir(path):
            cti_files = glob.glob(os.path.join(path, "*.cti"))
            specific_cti = [
                f
                for f in cti_files
                if "ic4" in f.lower()
                or "tis" in f.lower()
                or "theimagingsource" in f.lower()
            ]
            if specific_cti:
                print(
                    f"Found The Imaging Source GenTL producer in common location: {specific_cti[0]}"
                )
                return specific_cti[0]
            elif cti_files:
                print(
                    f"Found a generic GenTL producer in common location: {cti_files[0]}"
                )
                return cti_files[0]
    print(
        "Could not automatically find a suitable GenTL producer path through common locations or environment variables."
    )
    return None


def configure_camera(ia, model_name):
    """Configs the camera for full resolution based on its model."""
    print(f"Attempting to configure model: {model_name}")
    nm = ia.remote_device.node_map
    configured = True  # Assume success unless a critical setting fails

    try:
        #
        # 1) Common settings: disable auto‐exposure / auto‐gain
        #
        if hasattr(nm, "ExposureAuto") and "Off" in nm.ExposureAuto.symbolics:
            try:
                nm.ExposureAuto.value = "Off"
                print("  Disabled ExposureAuto")
            except Exception as e:
                print(f"  Warning: could not disable ExposureAuto: {e}")

        if hasattr(nm, "GainAuto") and "Off" in nm.GainAuto.symbolics:
            try:
                nm.GainAuto.value = "Off"
                print("  Disabled GainAuto")
            except Exception as e:
                print(f"  Warning: could not disable GainAuto: {e}")

        #
        # 2) Common numeric settings: exposure time & gain
        #
        if hasattr(nm, "ExposureTime"):
            try:
                nm.ExposureTime.value = 20000  # 20 ms
                print("  Set ExposureTime to 20 ms")
            except Exception as e:
                print(f"  Warning: could not set ExposureTime: {e}")

        if hasattr(nm, "Gain"):
            try:
                # enforce minimum if available
                if hasattr(nm.Gain, "min"):
                    min_gain = nm.Gain.min
                    try:
                        if nm.Gain.value < min_gain:
                            nm.Gain.value = min_gain
                    except Exception:
                        nm.Gain.value = min_gain
                print("  Gain configured")
            except Exception as e:
                print(f"  Warning: could not configure Gain: {e}")

        #
        # 3) Model-specific overrides
        #
        if DMK_33UP5000_MODEL_STR in model_name:
            print("Configuring DMK 33UP5000 specifics...")
            # pixel format, width, height
            for attr, val in [
                ("PixelFormat", DMK_33UP5000_PIXEL_FORMAT),
                ("Width", DMK_33UP5000_WIDTH),
                ("Height", DMK_33UP5000_HEIGHT),
            ]:
                if hasattr(nm, attr):
                    try:
                        node = getattr(nm, attr)
                        # for enums pick the desired or fallback to first choice
                        if hasattr(node, "symbolics") and val in node.symbolics:
                            node.value = val
                        else:
                            node.value = getattr(node, "symbolics", [val])[0]
                        print(f"  Set {attr} to {node.value}")
                    except Exception as e:
                        print(f"  Warning: could not set {attr}: {e}")

            # decimation
            for attr in ("DecimationHorizontal", "DecimationVertical"):
                if hasattr(nm, attr):
                    try:
                        node = getattr(nm, attr)
                        node.value = 1
                        print(f"  Set {attr} to 1")
                    except Exception as e:
                        print(f"  Warning: could not set {attr}: {e}")

        elif DMK_33UX250_MODEL_STR in model_name:
            print("Configuring DMK 33UX250 specifics...")
            # pixel format, width, height
            for attr, val in [
                ("PixelFormat", DMK_33UX250_PIXEL_FORMAT),
                ("Width", DMK_33UX250_WIDTH),
                ("Height", DMK_33UX250_HEIGHT),
            ]:
                if hasattr(nm, attr):
                    try:
                        node = getattr(nm, attr)
                        if hasattr(node, "symbolics") and val in node.symbolics:
                            node.value = val
                        else:
                            node.value = getattr(node, "symbolics", [val])[0]
                        print(f"  Set {attr} to {node.value}")
                    except Exception as e:
                        print(f"  Warning: could not set {attr}: {e}")

            # decimation & binning
            for attr in (
                "DecimationHorizontal",
                "DecimationVertical",
                "BinningHorizontal",
                "BinningVertical",
            ):
                if hasattr(nm, attr):
                    try:
                        node = getattr(nm, attr)
                        node.value = 1
                        print(f"  Set {attr} to 1")
                    except Exception as e:
                        print(f"  Warning: could not set {attr}: {e}")

        else:
            print(
                f"  Model {model_name} not explicitly supported; skipping full config."
            )
            configured = False

        #
        # 4) Final report
        #
        if configured:
            print(f"Camera {model_name} configured successfully.")
        else:
            print(f"Camera {model_name} not fully configured—check warnings above.")
        return configured

    except Exception as e:
        print(f"Error during camera configuration for {model_name}: {e}")
        import traceback

        traceback.print_exc()
        return False


def main():
    h = Harvester()
    ia = None
    try:
        gentl_producer_path = find_gentl_producer_path(
            specific_test_path=YOUR_SPECIFIC_GENTL_PATH
        )
        if gentl_producer_path:
            h.add_file(gentl_producer_path)
        h.update()

        if not h.device_info_list:
            print(
                "No cameras found. Ensure drivers are installed, camera connected, and GenTL path is correct or detectable."
            )
            return

        print("Available cameras:")
        for i, device_info in enumerate(h.device_info_list):
            print(f"  {i}: {device_info.model} (SN: {device_info.serial_number})")

        selected_index = 0
        if TARGET_SERIAL_NUMBER:
            # Code to select by serial number (omitted for brevity, same as before)
            pass

        if not h.device_info_list or selected_index >= len(h.device_info_list):
            print("No camera available for acquisition.")
            return

        device_info = h.device_info_list[selected_index]
        print(f"\nConnecting to: {device_info.model} (SN: {device_info.serial_number})")

        # Use h.create() instead of h.create_image_acquirer()
        ia = h.create(selected_index)

        if not configure_camera(ia, device_info.model):
            print("Critical camera configuration failed. Exiting.")
            return

        # --- START ACQUISITION ---
        fetch_timeout_seconds = 10
        try:
            ia.start()
            print("Image acquisition started (new API).")
        except Exception as e:
            print(
                f"Warning: start() failed, using deprecated start_image_acquisition(): {e}"
            )
            ia.start_image_acquisition()
            print("Image acquisition started (deprecated).")

        # small delay to let buffers queue up
        time.sleep(0.2)

        # --- FETCH A SINGLE FRAME ---
        print(f"Fetching image (will try for up to {fetch_timeout_seconds} seconds)...")
        buffer = None
        start_time = time.time()
        acquired_successfully = False

        while time.time() - start_time < fetch_timeout_seconds:
            try:
                # fetch_buffer(timeout) replaces try_fetch_buffer
                buffer = ia.fetch_buffer(timeout=2000)  # timeout in ms
                acquired_successfully = True
                break
            except Exception as fetch_exc:
                print(f"Fetch attempt warning/error: {fetch_exc}, retrying in 0.1s...")
                time.sleep(0.1)

        if not acquired_successfully or buffer is None:
            print(f"Failed to fetch image within {fetch_timeout_seconds} seconds.")
            # stop acquisition using whichever API works
            try:
                ia.stop()
            except:
                ia.stop_image_acquisition()
            return

        print("Image fetched successfully.")
        component = buffer.payload.components[0]
        height = component.height
        width = component.width
        pixel_format_str = component.data_format
        print(f"Image details: {width}x{height}, Format: {pixel_format_str}")
        image_data = component.data.reshape(height, width)

        image_to_save = image_data
        if image_data.dtype != np.uint8:
            if (
                "Mono10" in pixel_format_str
                or "Mono12" in pixel_format_str
                or "Mono16" in pixel_format_str
            ):
                if image_data.dtype == np.uint16:
                    shift_bits = max(0, image_data.itemsize * 8 - 8)
                    image_to_save = (image_data >> shift_bits).astype(np.uint8)
                else:
                    max_val = np.max(image_data)
                    image_to_save = (
                        (image_data / (max_val / 255.0)).astype(np.uint8)
                        if max_val > 0
                        else image_data.astype(np.uint8)
                    )
            else:
                image_to_save = image_data.astype(np.uint8)

        imageio.imwrite(OUTPUT_IMAGE_FILENAME, image_to_save)
        print(f"Image saved as {OUTPUT_IMAGE_FILENAME}")

        buffer.queue()
        print("Buffer queued.")

        ia.stop_image_acquisition()
        print("Image acquisition stopped.")

    except Exception as e:
        import traceback

        print(f"An unhandled error occurred in main: {e}")
        traceback.print_exc()
    finally:
        if ia:
            if ia.is_acquiring():
                try:
                    ia.stop_image_acquisition()
                    print("Image acquisition stopped in finally.")
                except Exception as e_stop:
                    print(f"Error stopping acquisition in finally: {e_stop}")
            try:
                ia.destroy()
                print("Image acquirer destroyed.")
            except Exception as e_destroy:
                print(f"Error destroying acquirer in finally: {e_destroy}")
        try:
            h.reset()
            print("Harvester reset.")
        except Exception as e_reset:
            print(f"Error resetting harvester in finally: {e_reset}")


if __name__ == "__main__":
    main()
