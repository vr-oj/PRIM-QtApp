# grab_one_frame.py  (version that uses ACQUISITION_START directly)

import imagingcontrol4 as ic4
import cv2
import time
import os


def main():
    # 1) Initialize IC4
    ic4.Library.init(api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR)
    print("Library.init() succeeded.")

    # 2) Open the first camera
    devices = ic4.DeviceEnum.devices()
    if not devices:
        print("No IC4 devices found.")
        ic4.Library.exit()
        return
    dev = devices[0]

    grabber = ic4.Grabber()
    grabber.device_open(dev)
    print(f"Opened camera: {dev.model_name} (S/N {dev.serial})")

    # 3) Apply settings (Mono8, Continuous, 10 FPS, 30 ms, gain=10)
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
            exp_node.value = 30000.0  # 30 ms = 30,000 µs
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

    # 4) Create QueueSink and start streaming immediately
    class DummyListener:
        def sink_connected(self, sink, pf, min_bufs_required):
            return True

        def sink_disconnected(self, sink):
            pass

    listener = DummyListener()
    sink = ic4.QueueSink(listener, [ic4.PixelFormat.Mono8], max_output_buffers=5)
    print("  → Created QueueSink (max 5 buffers).")

    # 5) stream_setup with ACQUISITION_START (camera start queueing internally)
    grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)
    print("  → Called stream_setup(ACQUISITION_START) → camera is now streaming.")

    # 6) Give the camera a short moment to fill buffers
    time.sleep(0.5)

    # 7) Pop one frame and save to disk as a TIFF
    try:
        buf = sink.pop_output_buffer(timeout=2000)  # wait up to 2 s
        arr = buf.numpy_wrap()  # Mono8 numpy array
        h, w = arr.shape

        # Save to a timestamped TIFF
        fname = f"frame_{int(time.time())}.tif"
        cv2.imwrite(fname, arr)
        print(f"  → Saved frame to {fname}")

        # Optional: show the captured frame for 1 second
        cv2.namedWindow("Captured Frame", cv2.WINDOW_NORMAL)
        cv2.imshow("Captured Frame", arr)
        cv2.waitKey(1000)
        cv2.destroyAllWindows()

        # Re‐queue the buffer (good practice)
        sink.queue_buffer(buf)
    except ic4.IC4Exception as e:
        print("  ✗ pop_output_buffer() error:", e)

    # 8) Clean up
    grabber.acquisition_stop()
    grabber.stream_stop()
    grabber.device_close()
    cv2.destroyAllWindows()
    del sink, grabber

    ic4.Library.exit()
    print("Done. Exiting.")


if __name__ == "__main__":
    main()
