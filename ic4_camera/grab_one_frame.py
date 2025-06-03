# grab_and_save.py
import imagingcontrol4 as ic4
import cv2
import time
import os


def main():
    # 1) Init IC4
    ic4.Library.init(api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR)
    print("Library.init() succeeded.")

    # 2) Open camera (using your default IC Capture profile)
    devices = ic4.DeviceEnum.devices()
    if not devices:
        print("No IC4 devices found.")
        ic4.Library.exit()
        return
    dev = devices[0]

    grabber = ic4.Grabber()
    grabber.device_open(dev)
    print(f"Opened camera: {dev.model_name} (S/N {dev.serial})")

    # 3) Apply the same settings you used before—Mono8, Continuous, 10 FPS, etc.
    try:
        pf_node = grabber.device_property_map.find_enumeration(ic4.PropId.PIXEL_FORMAT)
        if pf_node and "Mono8" in [e.name for e in pf_node.entries if e.is_available]:
            pf_node.value = "Mono8"
            print("  → Set PIXEL_FORMAT to Mono8")
    except Exception as e:
        print("  ✗ Could not set PIXEL_FORMAT:", e)

    try:
        acq_node = grabber.device_property_map.find_enumeration(
            ic4.PropId.ACQUISITION_MODE
        )
        if acq_node and "Continuous" in [e.name for e in acq_node.entries]:
            acq_node.value = "Continuous"
            print("  → Set ACQUISITION_MODE to Continuous")
    except Exception as e:
        print("  ✗ Could not set ACQUISITION_MODE:", e)

    try:
        fr_node = grabber.device_property_map.find_float(
            ic4.PropId.ACQUISITION_FRAME_RATE
        )
        if fr_node:
            fr_node.value = 10.0
            print("  → Set ACQUISITION_FRAME_RATE to 10.0")
    except Exception as e:
        print("  ✗ Could not set ACQUISITION_FRAME_RATE:", e)

    try:
        exp_node = grabber.device_property_map.find_integer(ic4.PropId.EXPOSURE_TIME)
        if exp_node:
            exp_node.value = 30000  # 30 ms = 30,000 µs
            print("  → Set EXPOSURE_TIME to 30 ms")
    except Exception as e:
        print("  ✗ Could not set EXPOSURE_TIME:", e)

    try:
        gain_node = grabber.device_property_map.find_float(ic4.PropId.GAIN)
        if gain_node:
            gain_node.value = 10
            print("  → Set GAIN to 10")
    except Exception as e:
        print("  ✗ Could not set GAIN:", e)

    # 4) Create QueueSink and attach a simple listener, queue a few buffers
    class DummyListener:
        def sink_connected(self, sink, pf, min_bufs_required):
            return True

        def sink_disconnected(self, sink):
            pass

    listener = DummyListener()
    sink = ic4.QueueSink(listener, [ic4.PixelFormat.Mono8], max_output_buffers=5)
    print("  → Created QueueSink")

    # 5) Defer acquisition start, then start it
    grabber.stream_setup(
        sink, setup_option=ic4.StreamSetupOption.DEFER_ACQUISITION_START
    )
    print("  → Called stream_setup(DEFER_ACQUISITION_START)")

    grabber.acquisition_start()
    print("  → Called acquisition_start() → camera streaming begins")

    # 6) Pop exactly one frame, save it to a TIFF, then exit
    try:
        buf = sink.pop_output_buffer()  # blocking until one frame arrives
        arr = buf.numpy_wrap()  # Mono8 array (HxW)
        h, w = arr.shape

        # Save to a timestamped TIFF in the current folder
        fname = "frame_{}.tif".format(int(time.time()))
        cv2.imwrite(fname, arr)
        print(f"  → Saved frame to {fname}")

        # Optionally, show it in a window for 1 second before closing
        cv2.namedWindow("Captured Frame", cv2.WINDOW_NORMAL)
        cv2.imshow("Captured Frame", arr)
        cv2.waitKey(1000)
        cv2.destroyAllWindows()

        # Requeue buffer (good practice)
        sink.queue_buffer(buf)
    except ic4.IC4Exception as e:
        print("  ✗ pop_output_buffer() error:", e)

    # 7) Clean up
    grabber.acquisition_stop()
    grabber.stream_stop()
    grabber.device_close()
    cv2.destroyAllWindows()
    del sink, grabber

    ic4.Library.exit()
    print("Done. Exiting.")


if __name__ == "__main__":
    main()
