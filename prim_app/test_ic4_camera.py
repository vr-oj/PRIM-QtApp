import imagingcontrol4 as ic4
import time
import logging

logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
)
log = logging.getLogger()


def run_test():
    try:
        ic4.Library.init()
        log.info("IC4 Library initialized.")

        devices = ic4.DeviceEnum.devices()
        if not devices:
            log.error("No devices found.")
            ic4.Library.exit()
            return

        target_device_info = devices[0]  # Try the first device
        log.info(
            f"Attempting to open device: {target_device_info.model_name} (SN: {target_device_info.serial or 'N/A'})"
        )

        grabber = ic4.Grabber()
        grabber.device_open(target_device_info)
        log.info("Device opened.")

        # Create a simple sink (no listener needed for this basic test)
        sink = ic4.QueueSink()
        log.info("QueueSink created.")

        log.info("Calling stream_setup...")
        grabber.stream_setup(sink)  # Use default options
        log.info("stream_setup completed.")

        if not grabber.is_acquisition_active:
            log.warning(
                "Acquisition not active after stream_setup. Attempting explicit start..."
            )
            grabber.acquisition_start()
            if not grabber.is_acquisition_active:
                log.error("Explicit acquisition_start also FAILED.")
                raise RuntimeError("Failed to start acquisition.")
            else:
                log.info("Explicit acquisition_start SUCCEEDED.")
        else:
            log.info("Acquisition IS active after stream_setup.")

        log.info("Attempting to grab a few frames...")
        frames_grabbed = 0
        for i in range(20):  # Try to get, say, 20 frames
            try:
                buffer = sink.pop_output_buffer()  # No timeout, blocking
                if buffer:
                    frames_grabbed += 1
                    log.info(
                        f"Frame {frames_grabbed} received! Dimensions: {buffer.image_type.width}x{buffer.image_type.height}, PixelFormat: {buffer.image_type.pixel_format}"
                    )
                    # Here you could inspect buffer.numpy_wrap() if needed
                    buffer.release()
                else:
                    log.warning("pop_output_buffer returned None/falsy.")
                    # This might happen if stream stops before 20 frames
                    break
                time.sleep(0.05)  # Roughly 20 FPS polling
            except ic4.IC4Exception as e_pop:
                log.error(
                    f"IC4Exception during pop_output_buffer: {e_pop} (Code: {e_pop.code})"
                )
                if e_pop.code == ic4.ErrorCode.NoData:
                    log.info("NoData from pop_output_buffer, continuing to poll...")
                    time.sleep(0.1)  # Wait a bit longer
                    continue
                else:
                    break  # Break on other IC4 errors

        log.info(f"Finished grabbing frames. Total frames received: {frames_grabbed}")

    except Exception as e:
        log.exception(f"An error occurred: {e}")
    finally:
        if "grabber" in locals() and grabber:
            if grabber.is_acquisition_active:
                log.info("Stopping acquisition...")
                grabber.acquisition_stop()
            if grabber.is_device_open:
                log.info("Closing device...")
                grabber.device_close()
        log.info("Exiting IC4 Library...")
        ic4.Library.exit()
        log.info("Test finished.")


if __name__ == "__main__":
    # IMPORTANT: Ensure GENICAM_GENTL64_PATH is set correctly in your environment
    # if you run this script directly, or set it via os.environ here.
    # Example:
    import os

    cti_path = "C:/Program Files/The Imaging Source Europe GmbH/IC4 GenTL Driver for USB3Vision Devices 1.4/bin/ic4-gentl-u3v_x64.cti"
    os.environ["GENICAM_GENTL64_PATH"] = os.path.dirname(cti_path)

    run_test()
