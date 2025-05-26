# Standalone IC4 Camera Test Script
import imagingcontrol4 as ic4
import cv2
import time
import logging
import os

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(name)s:%(lineno)d] - %(message)s",
)
log = logging.getLogger("IC4_Test")


def list_properties(grabber: ic4.Grabber):
    """Lists some common properties of the opened device."""
    log.info("--- Device Properties ---")
    pm = grabber.device_property_map
    common_props = {
        "Device Model Name": ic4.PropId.DEVICE_MODEL_NAME,
        "Device Vendor Name": ic4.PropId.DEVICE_VENDOR_NAME,
        "Device Serial Number": ic4.PropId.DEVICE_SERIAL_NUMBER,
        "Device User ID": ic4.PropId.DEVICE_USER_ID,
        "Width": ic4.PropId.WIDTH,
        "Height": ic4.PropId.HEIGHT,
        "Pixel Format": ic4.PropId.PIXEL_FORMAT,
        "Exposure Time": ic4.PropId.EXPOSURE_TIME,
        "Gain": ic4.PropId.GAIN,
        "Acquisition Frame Rate": ic4.PropId.ACQUISITION_FRAME_RATE,
    }
    for name, prop_id in common_props.items():
        try:
            if pm.is_available(prop_id):
                value = pm.get_value_str(prop_id)  # Get as string for simplicity
                # For specific types, you might use get_value_int, get_value_float etc.
                # value_type = pm.get_type(prop_id)
                # log.info(f"Property '{name}' type: {value_type}")
                # if value_type == ic4.PropType.INTEGER: value = pm.get_value_int(prop_id)
                # elif value_type == ic4.PropType.FLOAT: value = pm.get_value_float(prop_id)
                # elif value_type == ic4.PropType.ENUMERATION: value = pm.get_value_enum_entry(prop_id).symbolic
                # else: value = pm.get_value_str(prop_id)

                log.info(f"{name}: {value}")
            else:
                log.info(f"{name}: Not Available")
        except ic4.IC4Exception as e:
            log.warning(f"Could not get property {name}: {e}")
    log.info("-------------------------")


def main():
    grabber = None
    is_library_initialized = False

    try:
        # 1. Initialize IC4 Library
        log.info("Initializing IC4 library...")
        ic4.Library.init()
        is_library_initialized = True
        log.info("IC4 library initialized successfully.")

        # 2. Enumerate Devices
        device_list = ic4.DeviceEnum.devices()
        if not device_list:
            log.error(
                "No IC4 compatible camera devices found. Ensure SDK/drivers are installed and camera is connected."
            )
            return

        log.info(f"Found {len(device_list)} device(s):")
        for i, device_info in enumerate(device_list):
            log.info(
                f"  {i}: {device_info.model_name} (SN: {device_info.serial_number}, ID: {device_info.unique_name})"
            )

        # 3. User Camera Selection
        selected_device_info = None
        if len(device_list) == 1:
            selected_device_info = device_list[0]
            log.info(
                f"Automatically selected device: {selected_device_info.model_name}"
            )
        else:
            while True:
                try:
                    choice = int(
                        input(f"Select camera by number (0-{len(device_list)-1}): ")
                    )
                    if 0 <= choice < len(device_list):
                        selected_device_info = device_list[choice]
                        log.info(f"Selected device: {selected_device_info.model_name}")
                        break
                    else:
                        log.warning("Invalid choice. Please try again.")
                except ValueError:
                    log.warning("Invalid input. Please enter a number.")

        if not selected_device_info:
            log.error("No device selected.")
            return

        # 4. Open Device
        log.info(
            f"Opening device: {selected_device_info.model_name} (SN: {selected_device_info.serial_number})..."
        )
        grabber = ic4.Grabber(selected_device_info)
        grabber.device_open()
        log.info("Device opened successfully.")

        # 5. Display Device Info & Some Properties
        list_properties(grabber)
        pm = grabber.device_property_map

        # 6. Attempt to set a common pixel format (optional, for better display compatibility)
        # Try BGR8 (good for OpenCV), then RGB8, then Mono8
        preferred_formats = [
            ic4.PixelFormat.BGR8,
            ic4.PixelFormat.RGB8,
            ic4.PixelFormat.MONO8,
            # Add other Bayer formats if you want to test demosaicing
            # ic4.PixelFormat.BAYER_RG8,
        ]

        current_pixel_format_str = pm.get_value_str(ic4.PropId.PIXEL_FORMAT)
        log.info(f"Current PixelFormat: {current_pixel_format_str}")

        available_formats_symbols = []
        if (
            pm.is_available(ic4.PropId.PIXEL_FORMAT)
            and pm.get_type(ic4.PropId.PIXEL_FORMAT) == ic4.PropType.ENUMERATION
        ):
            available_formats_symbols = [
                entry.symbolic
                for entry in pm.get_available_enum_entries(ic4.PropId.PIXEL_FORMAT)
            ]
            log.info(f"Available PixelFormats: {available_formats_symbols}")

        set_format_success = False
        for fmt_id in preferred_formats:
            fmt_symbol = fmt_id.symbolic  # Get the string representation
            if fmt_symbol in available_formats_symbols:
                try:
                    log.info(f"Attempting to set PixelFormat to: {fmt_symbol}")
                    pm.set_value(
                        ic4.PropId.PIXEL_FORMAT, fmt_symbol
                    )  # Set by string symbol
                    set_format_success = True
                    log.info(
                        f"PixelFormat set to: {pm.get_value_str(ic4.PropId.PIXEL_FORMAT)}"
                    )
                    break
                except ic4.IC4Exception as e:
                    log.warning(f"Failed to set PixelFormat to {fmt_symbol}: {e}")
            else:
                log.info(
                    f"PixelFormat {fmt_symbol} not in available list for this device."
                )

        if not set_format_success:
            log.warning(
                f"Could not set any of the preferred pixel formats. Using current: {current_pixel_format_str}"
            )

        # 7. Setup Stream Sink
        log.info("Setting up stream sink...")
        sink = ic4.QueueSink()
        sink.frames_have_meta_data = True  # If you need metadata like timestamp

        # 8. Start Acquisition
        # Using ACQUISITION_START automatically starts acquisition.
        # stream_stop() will be needed before device_close().
        grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)
        log.info("Stream setup complete and acquisition started.")

        # 9. Capture Loop
        log.info("Starting frame capture loop (press 'q' in OpenCV window to quit)...")
        frames_to_capture = 200  # Capture a limited number of frames for testing
        frames_captured = 0
        window_name = f"IC4 Camera Test: {selected_device_info.model_name}"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)

        while frames_captured < frames_to_capture:
            try:
                # Timeout in milliseconds
                buf = sink.pop_output_buffer(1000)  # Wait up to 1 second for a buffer
                frames_captured += 1

                log.debug(
                    f"Frame {frames_captured}/{frames_to_capture} received. Size: {buf.width}x{buf.height}, Format: {buf.pixel_format.symbolic}"
                )

                # Convert buffer to NumPy array
                img_data = buf.numpy_wrap()  # This should give HxW or HxWxC

                # Display Frame (OpenCV)
                display_img = None
                pixel_format_enum = (
                    buf.pixel_format
                )  # This is an ic4.PixelFormat enum instance

                if pixel_format_enum == ic4.PixelFormat.MONO8:
                    display_img = img_data
                elif (
                    pixel_format_enum == ic4.PixelFormat.MONO10
                    or pixel_format_enum == ic4.PixelFormat.MONO12
                    or pixel_format_enum == ic4.PixelFormat.MONO16
                ):
                    # Normalize 10/12/16-bit mono to 8-bit for display
                    # This is a simple scaling, better methods exist for proper visualization
                    if img_data.dtype == "uint16":
                        display_img = cv2.convertScaleAbs(
                            img_data,
                            alpha=(
                                255.0 / img_data.max() if img_data.max() > 0 else 1.0
                            ),
                        )
                    else:  # Should not happen if format is MONO10/12/16
                        display_img = img_data
                elif (
                    pixel_format_enum == ic4.PixelFormat.BAYER_RG8
                ):  # Example for one Bayer pattern
                    display_img = cv2.cvtColor(img_data, cv2.COLOR_BAYER_RG2BGR)
                elif pixel_format_enum == ic4.PixelFormat.BAYER_BG8:
                    display_img = cv2.cvtColor(img_data, cv2.COLOR_BAYER_BG2BGR)
                elif pixel_format_enum == ic4.PixelFormat.BAYER_GR8:
                    display_img = cv2.cvtColor(img_data, cv2.COLOR_BAYER_GR2BGR)
                elif pixel_format_enum == ic4.PixelFormat.BAYER_GB8:
                    display_img = cv2.cvtColor(img_data, cv2.COLOR_BAYER_GB2BGR)
                elif pixel_format_enum == ic4.PixelFormat.RGB8:  # IC4 might give RGB
                    display_img = cv2.cvtColor(img_data, cv2.COLOR_RGB2BGR)
                elif pixel_format_enum == ic4.PixelFormat.BGR8:  # OpenCV native
                    display_img = img_data
                else:
                    log.warning(
                        f"Unsupported pixel format for display: {pixel_format_enum.symbolic}. Displaying raw if possible."
                    )
                    # Attempt to display first plane if multi-plane, or as is.
                    if img_data.ndim == 3 and img_data.shape[2] > 3:  # e.g. YUV formats
                        display_img = img_data[:, :, 0]  # Display Y plane
                    elif img_data.ndim == 2 or (
                        img_data.ndim == 3 and img_data.shape[2] in [1, 3, 4]
                    ):
                        display_img = (
                            img_data  # Try to display as is or let OpenCV handle it
                        )
                    else:
                        log.error(
                            f"Cannot determine how to display image with shape {img_data.shape}"
                        )

                if display_img is not None:
                    cv2.imshow(window_name, display_img)
                else:
                    log.warning(
                        f"display_img is None for format {pixel_format_enum.symbolic}"
                    )

                # Release buffer IMPORTANT!
                buf.release()

                if cv2.waitKey(10) & 0xFF == ord("q"):  # Wait 10ms, check for 'q'
                    log.info("'q' pressed, exiting capture loop.")
                    break

            except ic4.IC4Exception as e:
                if e.code == ic4.ErrorCode.TIMEOUT:
                    log.warning("Timeout waiting for frame buffer.")
                    # Optionally break or continue after a timeout
                    # if frames_captured > 0: # If we got some frames, maybe it's just end of stream
                    #    log.info("Timeout after capturing some frames, assuming stream ended or paused.")
                    #    break
                    continue
                else:
                    log.error(
                        f"IC4Exception during frame capture: {e} (Code: {e.code.name})"
                    )
                    break  # Exit loop on other IC4 errors
            except Exception as e:
                log.exception(f"Unexpected error during frame capture loop: {e}")
                break

        cv2.destroyAllWindows()

    except ic4.IC4Exception as e:
        log.error(
            f"IC4 Exception: {e} (Error Code: {e.code}, Description: {e.code.name})"
        )
    except (
        FileNotFoundError
    ) as e:  # Specifically for CTI not found during init (if that's how SDK reports it)
        log.error(
            f"Initialization File Error: {e}. Ensure GenTL producers are correctly installed and GENICAM_GENTL_PATH might be needed."
        )
    except Exception as e:
        log.exception(f"An unexpected error occurred: {e}")
    finally:
        # 10. Stop Acquisition and Cleanup
        log.info("Cleaning up resources...")
        if grabber:
            if grabber.is_acquisition_active():
                log.info("Stopping acquisition...")
                grabber.acquisition_stop()

            # stream_stop is needed if StreamSetupOption.ACQUISITION_START was used.
            # Check if stream is setup before trying to stop.
            # There isn't a direct 'is_stream_setup' but we can infer.
            # If stream_setup was called, sink would be associated.
            if (
                sink is not None and grabber.is_device_open()
            ):  # Check if device is open as stream ops need it
                try:
                    log.info("Stopping stream...")
                    grabber.stream_stop()  # Important if ACQUISITION_START was used
                except ic4.IC4Exception as e:
                    log.warning(
                        f"Error during stream_stop: {e} (This might be normal if stream was not fully started or already stopped)."
                    )

            if grabber.is_device_open():
                log.info("Closing device...")
                grabber.device_close()
            log.info("Device closed.")

        # 11. Exit IC4 Library
        if is_library_initialized:
            log.info("Exiting IC4 library...")
            ic4.Library.exit()
            log.info("IC4 library exited.")

        log.info("Test script finished.")


if __name__ == "__main__":
    main()
