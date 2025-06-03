# grab_one_frame.py (fixed version)

import imagingcontrol4 as ic4
import cv2
import time
import os


def main():
    # 1) Initialize IC4 library
    ic4.Library.init(api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR)
    print("Library.init() succeeded.")

    # 2) Find & open the first camera
    devices = ic4.DeviceEnum.devices()
    if not devices:
        print("No IC4 devices found.")
        ic4.Library.exit()
        return
    dev = devices[0]

    grabber = ic4.Grabber()
    grabber.device_open(dev)
    print(f"Opened camera: {dev.model_name} (S/N {dev.serial})")

    # 3) Apply acquisition settings (Mono8, Continuous, 10 FPS, 30 ms, gain = 10)
    try:
        pf_node = grabber.device_property_map.find_enumeration(ic4.PropId.PIXEL_FORMAT)
        if pf_node and "Mono8" in [e.name for e in pf_node.entries if e.is_available]:
            pf_node.value = "Mono8"
            print("  → Set PIXEL_FORMAT = Mono8")
    except Exception as e:
        print("  ✗ Cannot set PIXEL_FORMAT:", e)

    try:
        acq_node = grabber.device_property_map.find_enumeration(
            ic4.PropId.ACQUISITION_MODE
        )
        if acq_node and "Continuous" in [e.name for e in acq_node.entries]:
            acq_node.value = "Continuous"
            print("  → Set ACQUISITION_MODE = Continuous")
    except Exception as e:
        print("  ✗ Cannot set ACQUISITION_MODE:", e)

    try:
        fr_node = grabber.device_property_map.find_float(
            ic4.PropId.ACQUISITION_FRAME_RATE
        )
        if fr_node:
            fr_node.value = 10.0
            print("  → Set ACQUISITION_FRAME_RATE = 10.0 FPS")
    except Exception as e:
        print("  ✗ Cannot set ACQUISITION_FRAME_RATE:", e)

    try:
        exp_node = grabber.device_property_map.find_float(ic4.PropId.EXPOSURE_TIME)
        if exp_node:
            exp_node.value = 30000.0  # 30 ms = 30 000 µs
            print("  → Set EXPOSURE_TIME = 30 ms")
    except Exception as e:
        print("  ✗ Cannot set EXPOSURE_TIME:", e)

    try:
        gain_node = grabber.device_property_map.find_float(ic4.PropId.GAIN)
        if gain_node:
            gain_node.value = 10.0
            print("  → Set GAIN = 10.0")
    except Exception as e:
        print("  ✗ Cannot set GAIN:", e)

    # 4) Define a full DummyListener, including frames_queued()
    class DummyListener:
        def sink_connected(self, sink, pixel_format, min_buffers_required):
            # Return True so the sink actually attaches
            return True

        def sink_disconnected(self, sink):
            # Called when the sink is torn down—no action needed
            pass

        def frames_queued(self, sink):
            # Called whenever the sink’s internal queue has frames available
            # We don’t need to do anything here for a single-frame grab.
            pass

    listener = DummyListener()

    # 5) Create QueueSink (Mono8) with capacity 5
    sink = ic4.QueueSink(listener, [ic4.PixelFormat.Mono8], max_output_buffers=5)
    print("  → Created QueueSink (max 5 buffers).")

    # 6) Start streaming immediately—IC4 auto-allocates & queues buffers
    grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)
    print("  → Called stream_setup(ACQUISITION_START) → camera is now streaming.")

    # 7) Sleep a bit so at least one buffer can fill
    time.sleep(0.5)

    # 8) Pop exactly one frame and save to a TIFF
    try:
        # pop_output_buffer() blocks until a filled buffer is available
        buf = sink.pop_output_buffer()
        arr = buf.numpy_wrap()  # returns a NumPy array (Mono8) of shape (H, W)

        # Build a timestamped filename in the current folder
        fname = f"frame_{int(time.time())}.tif"
        cv2.imwrite(fname, arr)
        print(f"  → Saved frame to {fname}")

        # (Optional) Show the captured frame in an OpenCV window for 1 s
        cv2.namedWindow("Captured Frame", cv2.WINDOW_NORMAL)
        cv2.imshow("Captured Frame", arr)
        cv2.waitKey(1000)
        cv2.destroyAllWindows()

        # Re‐enqueue the buffer so the sink stays happy
        sink.queue_buffer(buf)
    except ic4.IC4Exception as e:
        print("  ✗ pop_output_buffer() error:", e)

    # 9) Clean up & exit
    grabber.acquisition_stop()
    grabber.stream_stop()
    grabber.device_close()
    cv2.destroyAllWindows()
    del sink, grabber

    ic4.Library.exit()
    print("Done. Exiting.")


if __name__ == "__main__":
    main()
