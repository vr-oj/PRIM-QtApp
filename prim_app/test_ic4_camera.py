import imagingcontrol4 as ic4
import time
import logging
import os  # For GENICAM_GENTL64_PATH

# Setup basic logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - [%(name)s:%(lineno)s] - %(message)s",
)
log = logging.getLogger("IC4Test")


class TestSinkListener(ic4.QueueSinkListener):
    def __init__(self):
        super().__init__()
        log.debug("TestSinkListener created.")

    # These signatures should match how they are called.
    # frame_ready and sink_connected are often called with userdata.
    # frames_queued and sink_disconnected are sometimes called without by some SDKs/wrappers.
    # The TypeError is the guide.

    def frame_ready(self, sink: ic4.QueueSink, buffer: ic4.ImageBuffer, userdata: any):
        # log.debug(f"TestSinkListener: Frame ready (callback).")
        pass

    def frames_queued(self, sink: ic4.QueueSink):  # Based on previous similar errors
        # log.debug(f"TestSinkListener: Frames queued.")
        pass

    def sink_connected(
        self, sink: ic4.QueueSink, image_type_proposed: ic4.ImageType, userdata: any
    ) -> bool:
        log.debug(
            f"TestSinkListener: Sink connected, proposed type: {image_type_proposed}"
        )
        return True

    def sink_disconnected(
        self, sink: ic4.QueueSink
    ):  # Corrected based on latest TypeError for this listener
        log.debug(f"TestSinkListener: Sink disconnected.")
        pass

    def sink_property_changed(
        self, sink: ic4.QueueSink, property_name: str, userdata: any
    ):
        pass


def run_ic4_test():
    grabber = None
    library_initialized = False
    try:
        # Set GENICAM_GENTL64_PATH
        # Ensure this path points to the directory containing your .cti file
        cti_file_path = "C:/Program Files/The Imaging Source Europe GmbH/IC4 GenTL Driver for USB3Vision Devices 1.4/bin/ic4-gentl-u3v_x64.cti"
        cti_dir = os.path.dirname(cti_file_path)

        current_gentl_path = os.environ.get("GENICAM_GENTL64_PATH", "")
        if cti_dir not in current_gentl_path.split(os.pathsep):
            log.info(f"Temporarily adding to GENICAM_GENTL64_PATH: {cti_dir}")
            if current_gentl_path:
                os.environ["GENICAM_GENTL64_PATH"] = (
                    f"{cti_dir}{os.pathsep}{current_gentl_path}"
                )
            else:
                os.environ["GENICAM_GENTL64_PATH"] = cti_dir
        log.debug(f"GENICAM_GENTL64_PATH is: {os.environ.get('GENICAM_GENTL64_PATH')}")

        ic4.Library.init()
        library_initialized = True
        log.info("IC4 Library initialized.")

        devices = ic4.DeviceEnum.devices()
        if not devices:
            log.error("No IC4 devices found.")
            return False  # Indicate failure

        target_device_info = devices[0]
        log.info(
            f"Attempting to open device: {target_device_info.model_name} (SN: {target_device_info.serial or 'N/A'})"
        )

        grabber = ic4.Grabber()
        grabber.device_open(target_device_info)
        log.info(f"Device '{target_device_info.model_name}' opened.")

        listener_instance = TestSinkListener()
        sink = ic4.QueueSink(listener=listener_instance)
        log.info("QueueSink created with listener.")

        log.info("Calling grabber.stream_setup(sink)...")
        grabber.stream_setup(sink)
        log.info("stream_setup call completed.")

        if not grabber.is_acquisition_active:
            log.warning(
                "Acquisition NOT active immediately after stream_setup. Attempting explicit acquisition_start()..."
            )
            grabber.acquisition_start()
            if not grabber.is_acquisition_active:
                log.error("Explicit acquisition_start() also FAILED.")
                raise RuntimeError(
                    "Failed to start camera acquisition after stream_setup and explicit start."
                )
            else:
                log.info("Explicit acquisition_start() SUCCEEDED.")
        else:
            log.info("Acquisition IS active immediately after stream_setup.")

        log.info("Attempting to grab frames...")
        frames_grabbed = 0
        max_frames_to_test = 50
        no_data_attempts = 0
        max_no_data_attempts = 200  # ~10-20 seconds of trying if timeout is 50-100ms

        for _ in range(
            max_frames_to_test * max_no_data_attempts // 10
        ):  # Generous loop limit
            if frames_grabbed >= max_frames_to_test:
                log.info(f"Successfully grabbed {max_frames_to_test} frames.")
                break

            buffer = None
            try:
                # pop_output_buffer(timeout_val_ms)
                # Using a timeout to prevent indefinite blocking if no frames arrive
                buffer = sink.pop_output_buffer(100)  # 100ms timeout

                if buffer:
                    no_data_attempts = 0  # Reset counter
                    frames_grabbed += 1
                    img_type = buffer.image_type
                    log.info(
                        f"Frame {frames_grabbed}/{max_frames_to_test} received! "
                        f"Type: {img_type.pixel_format}, Dim: {img_type.width}x{img_type.height}"
                    )
                    # To inspect data: arr = buffer.numpy_wrap()
                    buffer.release()
                else:  # Buffer is None (timeout occurred without error)
                    log.debug(
                        "pop_output_buffer timed out (returned None), no new frame yet."
                    )
                    no_data_attempts += 1

            except ic4.IC4Exception as e_pop:
                log.warning(
                    f"IC4Exception during pop_output_buffer: {e_pop} (Code: {e_pop.code})"
                )
                no_data_attempts += 1
                if e_pop.code not in [ic4.ErrorCode.NoData, ic4.ErrorCode.Timeout]:
                    log.error(
                        "Breaking grab loop due to unhandled IC4Exception from pop_output_buffer."
                    )
                    break  # Exit loop on critical IC4 errors from pop

            if no_data_attempts >= max_no_data_attempts:
                log.warning(
                    f"No data received after {max_no_data_attempts} attempts. Stopping test."
                )
                break

            time.sleep(0.01)  # Small delay to yield CPU, adjust as needed

        if frames_grabbed < max_frames_to_test:
            log.warning(
                f"Test finished, but only {frames_grabbed}/{max_frames_to_test} frames were grabbed."
            )
            return False  # Indicate potential issue
        else:
            log.info("Frame grabbing test completed successfully.")
            return True  # Indicate success

    except Exception as e:
        log.exception(f"An unexpected error occurred during the test: {e}")
        return False  # Indicate failure
    finally:
        if grabber:
            try:
                if grabber.is_acquisition_active:
                    log.info("Stopping acquisition (finally block)...")
                    grabber.acquisition_stop()
            except Exception as e_stop:
                log.error(f"Error stopping acquisition: {e_stop}")
            try:
                if grabber.is_device_open:
                    log.info("Closing device (finally block)...")
                    grabber.device_close()
            except Exception as e_close:
                log.error(f"Error closing device: {e_close}")

        if library_initialized:
            try:
                log.info("Exiting IC4 Library (finally block)...")
                ic4.Library.exit()
                log.info("IC4 Library exited.")
            except Exception as e_exit:
                log.error(f"Error exiting IC4 library: {e_exit}")

        log.info("Test script finished.")


if __name__ == "__main__":
    test_result = run_ic4_test()
    if test_result:
        log.info("Minimal IC4 test PASSED.")
    else:
        log.error("Minimal IC4 test FAILED or completed with warnings.")
