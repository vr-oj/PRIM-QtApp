# File: ic4_opencv_live_fixed.py

import cv2
import numpy as np
import imagingcontrol4 as ic4

#
# We need a minimal QueueSinkListener because the current QueueSink
# constructor no longer accepts a None listener.  As soon as
# sink_connected() returns True, IC4 will begin delivering frames.
#
class _DummyListener(ic4.QueueSinkListener):
    def __init__(self):
        super().__init__()

    def sink_connected(self, sink: ic4.QueueSink, image_type: ic4.ImageType, min_buffers_required: int) -> bool:
        # Return True to accept the format & start streaming
        return True

    def sink_disconnected(self, sink: ic4.QueueSink) -> None:
        # Called when the sink is torn down; we don’t need to do anything special
        pass

    def frames_queued(self, sink: ic4.QueueSink) -> None:
        # We will pull frames manually via pop_output_buffer() below,
        # so we don’t actually process them here.
        pass


def main():
    # ───────────────────────────────────────────────────────────────────────────
    # 1) Initialize IC4 library
    ic4.Library.init(api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR)

    try:
        # ─────────────────────────────────────────────────────────────────────────
        # 2) Enumerate all attached devices
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

        # ─────────────────────────────────────────────────────────────────────────
        # 3) Open the chosen device
        grabber = ic4.Grabber()
        grabber.device_open(dev)

        # ─────────────────────────────────────────────────────────────────────────
        # 4) Choose a PixelFormat that the camera supports (e.g. “Mono8” if available)
        pf_node = grabber.device_property_map.find_enumeration("PixelFormat")
        if pf_node:
            names = [e.name for e in pf_node.entries]
            pick = "Mono8" if "Mono8" in names else names[0]
            print(f"Setting PixelFormat = {pick}")
            pf_node.value = pick
        else:
            print("Warning: No PixelFormat node found; using default.")

        # ─────────────────────────────────────────────────────────────────────────
        # 5) Build a QueueSink + our dummy listener
        listener = _DummyListener()
        # Note: no longer “formats=[...]” keyword; just pass a list of PixelFormat enums
        sink = ic4.QueueSink(listener, [ic4.PixelFormat.Mono8], max_output_buffers=2)

        # ─────────────────────────────────────────────────────────────────────────
        # 6) Start streaming (stream_setup implicitly begins acquisition)
        grabber.stream_setup(sink)
        print("Streaming started. Press 'q' to quit.\n")

        # ─────────────────────────────────────────────────────────────────────────
        # 7) Main loop: pop buffers and display with OpenCV
        while True:
            try:
                buf = sink.pop_output_buffer()  # (no timeout argument now)
            except ic4.IC4Exception as e:
                # E.g. if the camera was unplugged or we hit a timeout
                print(f"Grab error: {e}")
                break

            # Convert the IC4 ImageBuffer into a numpy array.
            # Because we chose “Mono8,” buf.numpy_wrap() returns a 2D (height×width) uint8 array.
            raw = buf.numpy_wrap()    # shape = (height, width), dtype=uint8
            h = buf.height            # image height
            w = buf.width             # image width
            # (If you had chosen a 4-channel format like “BGRa8,” you’d reshape using stride.)

            # Display via OpenCV
            cv2.imshow("IC4 Mono8 Live", raw)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

        # ─────────────────────────────────────────────────────────────────────────
        # 8) Clean up: stop streaming, destroy windows
        grabber.stream_stop()
        cv2.destroyAllWindows()

    finally:
        # Always exit the IC4 library on shutdown
        ic4.Library.exit()


if __name__ == "__main__":
    main()