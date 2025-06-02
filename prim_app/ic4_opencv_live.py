# File: ic4_opencv_live_fixed.py

import cv2
import numpy as np
import imagingcontrol4 as ic4

def main():
    # 1) Initialize the IC4 library
    ic4.Library.init(api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR)

    try:
        # 2) List all attached IC4 devices
        device_list = ic4.DeviceEnum.devices()
        if len(device_list) == 0:
            print("No IC4 cameras found.")
            return

        print("Found camera:")
        for i, dev in enumerate(device_list):
            print(f"  [{i}] {dev.model_name}  (SN {dev.serial})")
        idx = 0
        print(f"Selecting index [{idx}] automatically.\n")
        dev = device_list[idx]

        # 3) Open the selected device
        grabber = ic4.Grabber()
        grabber.device_open(dev)

        # 4) Pick a PixelFormat that’s supported (e.g. Mono8 if available),
        #    and leave Width/Height alone (camera’s defaults are usually max).
        pf_node = grabber.device_property_map.find_enumeration("PixelFormat")
        if pf_node:
            names = [e.name for e in pf_node.entries]
            # prefer “Mono8” if it exists, else pick the first entry:
            pick = "Mono8" if "Mono8" in names else names[0]
            print(f"Setting PixelFormat = {pick}")
            pf_node.value = pick
        else:
            print("Warning: No PixelFormat node found; using whatever default.")

        # 5) Create a QueueSinkListener (we don’t need special processing, so listener can be None)
        sink = ic4.QueueSink(None, [ic4.PixelFormat.Mono8], max_output_buffers=2)

        # 6) Tell the grabber to start streaming to our sink
        grabber.stream_setup(sink)
        print("Streaming started. Press 'q' to quit.\n")

        # 7) Main loop: pop buffers, convert to NumPy, show via OpenCV
        while True:
            try:
                buf = sink.pop_output_buffer()  # no timeout arg any more
            except ic4.IC4Exception as e:
                # A timeout or device‐lost will raise here
                print(f"Grab error: {e}")
                break

            # Convert the IC4 ImageBuffer into a NumPy array
            # (Mono8 means one channel per pixel)
            raw = buf.numpy_wrap()         # view of shape (height, width), dtype=uint8
            h = buf.height                 # current height
            w = buf.width                  # current width
            stride = buf.stride            # bytes per row

            # raw is already (h×w) for Mono8. If you picked a 4-channel format (BGRa8),
            # you’d get a (h, stride) buffer‐view, reshape into (h, w, 4), etc.

            # Display via OpenCV
            cv2.imshow("IC4 Mono8 Live", raw)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break

        # 8) Clean up
        grabber.stream_stop()  # stop streaming
        cv2.destroyAllWindows()

    finally:
        ic4.Library.exit()


if __name__ == "__main__":
    main()