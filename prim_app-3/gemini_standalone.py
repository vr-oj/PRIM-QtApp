import imagingcontrol4 as ic4
import os
import time
import tkinter as tk
from tkinter import filedialog
import cv2  # For live view and image saving
import numpy as np  # For image manipulation

# Setup basic logging for the script
import logging

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
log = logging.getLogger(__name__)


def select_cti_file():
    """Prompts the user to select a .cti file."""
    root = tk.Tk()
    root.withdraw()  # Hide the main tkinter window
    cti_path = filedialog.askopenfilename(
        title="Select GenTL Producer File (.cti)",
        filetypes=(("CTI files", "*.cti"), ("All files", "*.*")),
    )
    root.destroy()
    if not cti_path:
        log.error("No CTI file selected. Exiting.")
        return None
    log.info(f"Selected CTI file: {cti_path}")
    return cti_path


def initialize_ic4(cti_path):
    """Sets GENICAM_GENTL64_PATH and initializes the IC4 library."""
    if not os.path.exists(cti_path):
        log.error(f"CTI file not found at {cti_path}")
        return False

    cti_dir = os.path.dirname(cti_path)
    log.info(f"Setting GENICAM_GENTL64_PATH to: {cti_dir}")
    # Note: For robustness, one might check existing GENICAM_GENTL64_PATH
    # and append/prepend rather than overwrite, but for a standalone script,
    # direct setting is often sufficient.
    os.environ["GENICAM_GENTL64_PATH"] = cti_dir

    try:
        ic4.Library.init()
        log.info("IC4 Library initialized successfully.")
        return True
    except Exception as e:
        log.error(f"Failed to initialize IC4 Library: {e}")
        return False


def select_camera(devices):
    """Allows user to select a camera if multiple are found."""
    if not devices:
        log.error("No camera devices found.")
        return None

    if len(devices) == 1:
        log.info(
            f"Automatically selecting the only available camera: {devices[0].model_name} (SN: {devices[0].serial or 'N/A'})"
        )
        return devices[0]
    else:
        log.info("Multiple cameras found:")
        for i, dev_info in enumerate(devices):
            print(
                f"  [{i}] {dev_info.model_name} (SN: {dev_info.serial or 'N/A'}, UniqueName: {dev_info.unique_name or 'N/A'})"
            )

        while True:
            try:
                choice_str = input(f"Select camera by number (0-{len(devices)-1}): ")
                choice = int(choice_str)
                if 0 <= choice < len(devices):
                    selected_dev = devices[choice]
                    log.info(
                        f"Selected camera: {selected_dev.model_name} (SN: {selected_dev.serial or 'N/A'})"
                    )
                    return selected_dev
                else:
                    print("Invalid choice. Please try again.")
            except ValueError:
                print("Invalid input. Please enter a number.")
            except EOFError:  # Handle Ctrl+D or similar abrupt exit from input
                log.warning("Camera selection aborted.")
                return None


def display_camera_properties(device_object):
    """Displays detailed information about camera properties from an ic4.Device object."""
    if not device_object:
        log.error("No device object to display properties for.")
        return

    model_name = "UnknownModel"
    serial_num = "UnknownSN"
    try:  # Get model and serial from the DeviceInfo if possible, or fallback
        # The device_object itself doesn't directly store DeviceInfo,
        # but we can get its map which is usually tied to model/serial context
        # For robust display name, one might pass DeviceInfo along with Device object
        # For now, we'll assume the property map context implies the device.
        # The Device object has a property_map attribute.
        pass
    except:
        pass

    log.info(
        f"\n====== Camera Properties ======"
    )  # Simpler title without model/SN if not easily available from device_object

    prop_map = device_object.property_map

    try:
        # Fetch all property items. Note: prop_map.properties() might return an iterator/generator
        # It's safer to convert to a list if sorting or multiple passes are needed.
        # However, direct iteration is usually fine for display.
        all_prop_items = list(prop_map.properties())  # Convert to list for sorting
        properties_to_display = sorted(all_prop_items, key=lambda p: p.name)
    except Exception as e:
        log.error(
            f"Could not retrieve or sort properties: {e}. Will attempt to iterate directly."
        )
        try:
            properties_to_display = prop_map.properties()  # Fallback to direct iterator
        except Exception as e_iter:
            log.error(f"Could not iterate properties: {e_iter}")
            print("===========================================================\n")
            return

    for prop_item in properties_to_display:
        try:
            prop_name = prop_item.name
            prop_type_str = prop_item.type_name

            current_value_str = "(N/A)"
            if prop_map.is_readable(prop_name):
                try:
                    current_value_str = prop_map.get_value_str(prop_name)
                except Exception:
                    try:
                        val = prop_map.get_value(
                            prop_name
                        )  # For types not well string-represented
                        current_value_str = str(val)
                    except Exception as e_val_fb:
                        current_value_str = f"(Error fetching value: {e_val_fb})"
            else:
                current_value_str = "(Not Readable)"

            is_readonly = prop_map.is_readonly(prop_name)
            is_writable = prop_map.is_writable(prop_name)

            prop_info_parts = [
                f"  Property: {prop_name:<30}",  # Pad for alignment
                f"Type: {prop_type_str:<15}",
                f"Value: {current_value_str}",
                f"Readonly: {is_readonly}",
                f"Writable: {is_writable}",
            ]

            prop_type_enum = prop_item.type
            if (
                prop_type_enum == ic4.PropertyType.INTEGER
                or prop_type_enum == ic4.PropertyType.FLOAT
            ):
                if prop_map.is_readable(
                    prop_name
                ):  # Min/Max only make sense if readable
                    try:
                        min_val = prop_map.get_minimum(prop_name)
                        max_val = prop_map.get_maximum(prop_name)
                        prop_info_parts.append(f"Range: [{min_val} - {max_val}]")
                        if prop_type_enum == ic4.PropertyType.INTEGER:
                            inc_val = prop_map.get_increment(prop_name)
                            if inc_val is not None:
                                prop_info_parts.append(f"Increment: {inc_val}")
                    except Exception:
                        pass  # Ignore if range/inc info not available

            elif prop_type_enum == ic4.PropertyType.ENUMERATION:
                if prop_map.is_readable(prop_name):
                    try:
                        options = list(
                            prop_map.get_available_enumeration_values_str(prop_name)
                        )
                        prop_info_parts.append(f"Options: {options}")
                    except Exception:
                        pass

            elif prop_type_enum == ic4.PropertyType.COMMAND:
                prop_info_parts.append(
                    "Action: (Command - not executed by this display)"
                )

            print(" | ".join(prop_info_parts))
        except Exception as e:
            prop_name_fb = "UnknownProperty"
            try:
                prop_name_fb = prop_item.name
            except:
                pass
            log.warning(
                f"Could not display full details for property '{prop_name_fb}': {e}"
            )
    print("===========================================================\n")


def take_snapshot(grabber, device_name_for_file):
    """Takes a single snapshot, displays it, and saves it."""
    log.info("Configuring for snapshot...")
    sink = None
    try:
        # Example: Attempt to set a common, easily viewable format if possible.
        # This requires the device to be open on the grabber, which it is.
        device_object = grabber.device_get()  # Get the ic4.Device object
        if device_object:
            pm = device_object.property_map
            try:
                # Try to set to Mono8 or a common color format
                available_formats = list(
                    pm.get_available_enumeration_values_str("PixelFormat")
                )
                if "Mono8" in available_formats:
                    pm.set_value_str("PixelFormat", "Mono8")
                    log.info("Set PixelFormat to Mono8 for snapshot.")
                elif (
                    "BGR8" in available_formats
                ):  # BGR8 is common for color cameras to be OpenCV friendly
                    pm.set_value_str("PixelFormat", "BGR8")
                    log.info("Set PixelFormat to BGR8 for snapshot.")
            except Exception as e_pf:
                log.warning(f"Could not set default PixelFormat for snapshot: {e_pf}")

        sink = ic4.SnapSink()
        # AcquireLatestImage helps if camera was streaming or has old frames.
        grabber.stream_setup(sink, ic4.StreamSetupOption.AcquireLatestImage)

        log.info("Snapping single image...")
        buffer = sink.snap_single(timeout_ms=5000)  # 5-second timeout

        if buffer and buffer.is_valid:
            img_type = buffer.image_type
            log.info(
                f"Snapshot successful! Image: {img_type.width}x{img_type.height}, Format: {img_type.pixel_format_name}"
            )

            img_array = buffer.numpy_wrap()

            filename_base = (
                f"snapshot_{device_name_for_file}_{time.strftime('%Y%m%d_%H%M%S')}"
            )
            img_to_save_or_show = None

            if (
                img_type.pixel_format_name == "Mono8"
                or img_type.pixel_format_name == "Mono10"
                or img_type.pixel_format_name == "Mono12"
                or img_type.pixel_format_name == "Mono16"
            ):
                # For display, scale Mono10/12/16 to 8-bit if needed, or display as is if cv2 handles it
                if img_array.dtype != np.uint8:
                    img_to_save_or_show = cv2.normalize(
                        img_array, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U
                    )
                else:
                    img_to_save_or_show = img_array
                filename_ext = ".png"
            elif (
                img_type.pixel_format_name == "BGR8"
                or img_type.pixel_format_name == "RGB8"
            ):  # BGR8 is cv2 native for color
                img_to_save_or_show = img_array
                if (
                    img_type.pixel_format_name == "RGB8"
                ):  # Convert RGB to BGR for OpenCV
                    img_to_save_or_show = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
                filename_ext = ".png"
            # Add more pixel format conversions as needed (e.g., Bayer to BGR)
            # For Bayer formats (e.g., BayerRG8), conversion is needed:
            elif "Bayer" in img_type.pixel_format_name:
                log.info(
                    f"Attempting to demosaic Bayer format: {img_type.pixel_format_name}"
                )
                # Determine Bayer conversion code (this is simplified)
                # E.g. BayerRG8 -> cv2.COLOR_BAYER_RG2BGR
                # This requires knowing the exact bayer pattern.
                # For simplicity, we'll try a common one or save raw.
                # cvt_code = cv2.COLOR_BAYER_RG2BGR # Example, adjust based on actual format
                # try:
                #    img_to_save_or_show = cv2.cvtColor(img_array, cvt_code)
                #    filename_ext = ".png"
                # except Exception as e_bayer:
                log.warning(
                    f"Bayer format {img_type.pixel_format_name} received. Display/save might be raw or incorrect without specific demosaicing. Saving as .npy."
                )
                img_to_save_or_show = img_array  # Keep original for .npy
                filename_ext = ".npy"
            else:
                log.warning(
                    f"Unhandled pixel format for display/PNG saving: {img_type.pixel_format_name}. Saving as .npy."
                )
                img_to_save_or_show = img_array
                filename_ext = ".npy"

            filename = f"{filename_base}{filename_ext}"

            try:
                if filename_ext == ".npy":
                    np.save(filename, img_to_save_or_show)
                    log.info(f"Snapshot raw data saved as {filename}")
                elif cv2.imwrite(filename, img_to_save_or_show):
                    log.info(f"Snapshot image saved as {filename}")
                else:
                    log.error(f"Failed to save snapshot as {filename} using OpenCV.")

                # Display the image if it's displayable
                if filename_ext != ".npy" and img_to_save_or_show is not None:
                    cv2.imshow(
                        f"Snapshot - {device_name_for_file}", img_to_save_or_show
                    )
                    log.info(
                        "Displaying snapshot. Press any key in the image window to close."
                    )
                    cv2.waitKey(0)
                    cv2.destroyWindow(f"Snapshot - {device_name_for_file}")

            except Exception as e_save_disp:
                log.error(f"Error saving or displaying image: {e_save_disp}")

            buffer.release()
        else:
            log.error("Failed to snap image or buffer was invalid.")

    except ic4.IC4Exception as e:
        log.error(f"IC4Exception during snapshot: {e} (Code: {e.code})")
    except Exception as e:
        log.error(f"Generic error during snapshot: {e}")
        import traceback

        traceback.print_exc()


class SimpleSinkListener(ic4.QueueSinkListener):
    """Basic listener for QueueSink, primarily for logging/debugging."""

    def __init__(self, owner_name="LiveFeedListener"):
        super().__init__()
        self.owner_name = owner_name
        self.frame_count = 0

    def frame_ready(self, sink: ic4.QueueSink, buffer: ic4.ImageBuffer, userdata: any):
        self.frame_count += 1

    def sink_connected(
        self, sink: ic4.QueueSink, image_type_proposed: ic4.ImageType, userdata: any
    ) -> bool:
        log.info(
            f"Listener '{self.owner_name}': Sink connected. Proposed: {image_type_proposed}. Accepting."
        )
        return True

    def frames_queued(self, sink: ic4.QueueSink):
        pass

    def sink_disconnected(self, sink: ic4.QueueSink):
        log.info(f"Listener '{self.owner_name}': Sink disconnected.")
        pass

    def sink_property_changed(
        self, sink: ic4.QueueSink, property_name: str, userdata: any
    ):
        pass


def show_live_feed(grabber, device_name_for_file):
    """Shows a simple live feed using OpenCV."""
    log.info("Configuring for live feed...")
    sink = None
    listener = None
    cv2_window_name = f"Live Feed - {device_name_for_file} (Press 'q' to quit)"

    try:
        device_object = grabber.device_get()
        if device_object:
            pm = device_object.property_map
            try:
                available_formats = list(
                    pm.get_available_enumeration_values_str("PixelFormat")
                )
                target_format = None
                if "Mono8" in available_formats:
                    target_format = "Mono8"
                elif "BGR8" in available_formats:
                    target_format = "BGR8"
                # Add more preferred formats if needed

                if target_format:
                    pm.set_value_str("PixelFormat", target_format)
                    log.info(
                        f"Attempted to set PixelFormat to {target_format} for live feed."
                    )
                else:
                    log.info(
                        f"PixelFormat not set to Mono8/BGR8. Current: {pm.get_value_str('PixelFormat')}"
                    )

            except Exception as e_pf:
                log.warning(f"Could not set default PixelFormat for live feed: {e_pf}")

        listener = SimpleSinkListener()
        sink = ic4.QueueSink(listener=listener)

        grabber.stream_setup(sink)  # Default options
        log.info("Stream setup complete for live feed.")

        if not grabber.is_acquisition_active:
            log.info("Starting acquisition for live feed...")
            grabber.acquisition_start()
            if not grabber.is_acquisition_active:
                log.error("Failed to start acquisition for live feed.")
                return
        log.info("Acquisition started.")

        while True:
            buffer = None
            display_img = None
            try:
                buffer = sink.pop_output_buffer(
                    timeout_ms=30
                )  # Short timeout for responsive UI
                if buffer and buffer.is_valid:
                    img_array = buffer.numpy_wrap()
                    img_type = buffer.image_type

                    if img_type.pixel_format_name == "Mono8":
                        display_img = img_array
                    elif img_type.pixel_format_name == "BGR8":
                        display_img = img_array
                    elif img_type.pixel_format_name == "RGB8":
                        display_img = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
                    elif "Bayer" in img_type.pixel_format_name:
                        # Simple demosaic, might need specific cvt_code for correct colors
                        # Example for BayerRG8, actual code depends on the specific pattern
                        # cvt_code = cv2.COLOR_BAYER_RG2BGR
                        # try: display_img = cv2.cvtColor(img_array, cvt_code)
                        # except: display_img = img_array # Show raw bayer if conversion fails
                        log.debug(
                            f"Displaying Bayer image ({img_type.pixel_format_name}) directly or with basic demosaic attempt."
                        )
                        # For a robust solution, you'd map specific Bayer formats to cv2.COLOR_BAYER_**2BGR codes
                        # As a fallback, just show the raw bayer data, it will look monochrome-ish and patterned
                        if img_array.dtype != np.uint8:  # Scale if not 8-bit
                            display_img = cv2.normalize(
                                img_array,
                                None,
                                0,
                                255,
                                cv2.NORM_MINMAX,
                                dtype=cv2.CV_8U,
                            )
                        else:
                            display_img = img_array
                    elif img_array.ndim == 2:  # Other grayscale types
                        if img_array.dtype != np.uint8:
                            display_img = cv2.normalize(
                                img_array,
                                None,
                                0,
                                255,
                                cv2.NORM_MINMAX,
                                dtype=cv2.CV_8U,
                            )
                        else:
                            display_img = img_array
                    elif (
                        img_array.ndim == 3 and img_array.shape[2] == 1
                    ):  # Mono in 3D array
                        temp_img = img_array[:, :, 0]
                        if temp_img.dtype != np.uint8:
                            display_img = cv2.normalize(
                                temp_img, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U
                            )
                        else:
                            display_img = temp_img
                    else:
                        log.debug(
                            f"Unsupported format for live display: {img_type.pixel_format_name}"
                        )

                    if display_img is not None:
                        cv2.imshow(cv2_window_name, display_img)
                    buffer.release()

                key = (
                    cv2.waitKey(1) & 0xFF
                )  # waitKey(1) is crucial for imshow to refresh
                if key == ord("q"):
                    log.info("'q' pressed. Stopping live feed.")
                    break
                # Check if window was closed by user (often getWindowProperty returns -1 if closed)
                if cv2.getWindowProperty(cv2_window_name, cv2.WND_PROP_VISIBLE) < 1:
                    log.info("Live feed window was closed by user.")
                    break

            except ic4.IC4Exception as e_pop:
                if (
                    e_pop.code == ic4.ErrorCode.Timeout
                    or e_pop.code == ic4.ErrorCode.NoData
                ):
                    # This is normal if camera FPS is low or processing is slow
                    # Continue loop to keep checking for 'q' or window close
                    if (
                        cv2.getWindowProperty(cv2_window_name, cv2.WND_PROP_AUTOSIZE)
                        == -1
                    ):  # Check if window still exists
                        log.info(
                            "Live feed window seems to have been closed (check during timeout)."
                        )
                        break
                    pass
                else:  # Other IC4 errors
                    log.error(
                        f"IC4Exception during live feed buffer pop: {e_pop} (Code: {e_pop.code})"
                    )
                    break
            except Exception as e_generic_loop:
                log.error(f"Generic error in live feed loop: {e_generic_loop}")
                if buffer and hasattr(buffer, "release"):
                    buffer.release()  # Ensure buffer is released
                break

        log.info(
            f"Live feed finished. Total frames processed by listener: {listener.frame_count}"
        )

    except Exception as e:
        log.error(f"Error setting up or running live feed: {e}")
        import traceback

        traceback.print_exc()
    finally:
        if grabber and grabber.is_acquisition_active:
            log.info("Stopping acquisition (live feed cleanup)...")
            grabber.acquisition_stop()
        cv2.destroyAllWindows()  # Close any OpenCV windows
        log.info("Live feed resources (OpenCV windows) cleaned up.")


def main():
    cti_file = None
    library_initialized = False
    grabber = None
    device_is_open = False  # Flag to track if device_open was successful
    selected_device_info_obj = None  # To store the ic4.DeviceInfo object

    try:
        cti_file = select_cti_file()
        if not cti_file:
            return

        if not initialize_ic4(cti_file):
            return
        library_initialized = True

        devices = ic4.DeviceEnum.devices()
        selected_device_info_obj = select_camera(devices)

        if not selected_device_info_obj:
            return

        grabber = ic4.Grabber()
        log.info(
            f"Attempting to open device: {selected_device_info_obj.model_name} (SN: {selected_device_info_obj.serial or 'N/A'})"
        )

        # device_open() returns an ic4.Device object, or None on failure.
        device_object_instance = grabber.device_open(selected_device_info_obj)

        if not device_object_instance:  # Check if None
            log.error(
                f"Failed to open device {selected_device_info_obj.model_name}. `grabber.device_open()` returned None."
            )
            return

        log.info(f"Device {selected_device_info_obj.model_name} opened successfully.")
        device_is_open = True  # Set flag

        # Pass the successfully opened ic4.Device object for property display
        display_camera_properties(device_object_instance)

        # Create a string for filenames from model and serial
        device_name_for_file = f"{selected_device_info_obj.model_name.replace(' ', '_').replace('-', '_')}_{selected_device_info_obj.serial or 'NoSN'}"

        while True:
            try:
                action = (
                    input("Choose action: (s)napshot, (l)ive feed, or (q)uit? ")
                    .strip()
                    .lower()
                )
            except EOFError:
                action = "q"  # Treat EOF as quit
                print("\nEOF detected, quitting.")

            if action == "s":
                take_snapshot(
                    grabber, device_name_for_file
                )  # grabber has the opened device
                # After snapshot, could ask again or quit. For simplicity, we'll quit.
                break
            elif action == "l":
                show_live_feed(
                    grabber, device_name_for_file
                )  # grabber has the opened device
                # After live feed, quit.
                break
            elif action == "q":
                log.info("Quitting as per user request.")
                break
            else:
                print("Invalid choice. Please enter 's', 'l', or 'q'.")

    except Exception as e:
        log.error(f"An unexpected error occurred in main: {e}")
        import traceback

        traceback.print_exc()
    finally:
        log.info("Initiating cleanup sequence...")
        if grabber:
            # Only call device_close if the device was successfully opened
            if device_is_open and grabber.is_device_open:
                log.info("Closing device...")
                try:
                    grabber.device_close()
                    log.info("Device closed.")
                except Exception as e_close:
                    log.error(f"Exception during device_close: {e_close}")
            elif (
                device_is_open
            ):  # If flag is true but is_device_open is false (should not happen if logic is correct)
                log.warning(
                    "Device was marked as open, but grabber.is_device_open is false. Skipping explicit close."
                )
            else:  # Device was never opened
                log.info(
                    "Device was not opened or already handled. No explicit close needed via grabber."
                )
        else:
            log.info("Grabber was not instantiated.")

        if library_initialized:
            log.info("Exiting IC4 library...")
            try:
                ic4.Library.exit()
                log.info("IC4 Library exited.")
            except Exception as e_exit:
                log.error(f"Exception during Library.exit: {e_exit}")

        cv2.destroyAllWindows()  # Ensure any stray OpenCV windows are closed
        log.info("Script finished and cleaned up.")


if __name__ == "__main__":
    main()
