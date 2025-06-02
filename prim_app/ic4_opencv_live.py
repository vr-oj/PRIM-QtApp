# File: ic4_opencv_live_fixed.py

import cv2
import numpy as np
import imagingcontrol4 as ic4

#
# A minimal listener that allocates some buffers as soon as
# IC4 asks “can I connect?”, and then returns True so that
# streaming can start.
#
class _DummyListener(ic4.QueueSinkListener):
    def __init__(self):
        super().__init__()

    def sink_connected(
        self,
        sink: ic4.QueueSink,
        image_type: ic4.ImageType,
        min_buffers_required: int,
    ) -> bool:
        # We must allocate at least min_buffers_required, but it's
        # safe to ask for a few more.  Five is usually fine.
        sink.alloc_and_queue_buffers(5)
        return True

    def sink_disconnected(self, sink: ic4.QueueSink) -> None:
        # Called when the sink is torn down; we don’t need to do anything special here.
        pass

    def frames_queued(self, sink: ic4.QueueSink) -> None:
        # We will manually pop frames in our main() loop, so we don't do anything here.
        pass


def main():
    # ───────────────────────────────────────────────────────────────────────────
    # 1) Initialize the IC4 library.  (Always match with Library.exit() at the end.)
    ic4.Library.init(api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR)

    try:
        # ─────────────────────────────────────────────────────────────────────────
        # 2) Enumerate attached IC4 cameras
        device_list = ic4.DeviceEnum.devices()
        if not device_list:
            print("No IC4 cameras found.")
            return

        print("Found camera:")
        for i, dev in enumerate(device_list):
            print(f"  [{i}] {dev.model_name}  (SN {dev.serial})")
        idx = 0
        print(f"Selecting index [{idx}] automatically.\n")
        dev = device_list[idx]

        # ─────────────────────────────────────────────────────────────────────────
        # 3) Open the chosen camera
        grabber = ic4.Grabber()
        grabber.device_open(dev)

        # ─────────────────────────────────────────────────────────────────────────
        # 4) Pick a PixelFormat (Mono8 if available, else the first entry)
        pf_node = grabber.device_property_map.find_enumeration("PixelFormat")
        if pf_node:
            names = [entry.name for entry in pf_node.entries]
            pick = "Mono8" if "Mono8" in names else names[0]
            print(f"Setting PixelFormat = {pick}")
            pf_node.value = pick
        else:
            print("Warning: No PixelFormat node found; using whatever the driver default is.")

        # ─────────────────────────────────────────────────────────────────────────
        # 5) Build a QueueSink + our dummy listener.  Pass a list of PixelFormat enums.
        listener = _DummyListener()
        sink = ic4.QueueSink(listener, [ic4.PixelFormat.Mono8], max_output_buffers=5)

        # ─────────────────────────────────────────────────────────────────────────
        # 6) Start streaming.  stream_setup() automatically begins acquisition.
        grabber.stream_setup(sink)
        print("Streaming started. Press 'q' to quit.\n")

        # ─────────────────────────────────────────────────────────────────────────
        # 7) Main loop: pop buffers and display via OpenCV
        while True:
            try:
                buf = sink.pop_output_buffer()  # no timeout argument in v1.3.0
            except ic4.IC4Exception as e:
                # If there is truly no data yet, we get ErrorCode.NoData.  Just loop again.
                if e.code == ic4.Error.NoData:
                    continue
                print(f"Grab error: {e}")
                break

            # Because we asked for Mono8, buf.numpy_wrap() returns a 2D numpy array (height×width, dtype=uint8)
            raw = buf.numpy_wrap()  # shape = (height, width), dtype=uint8
            h = buf.height          # height in pixels
            w = buf.width           # width in pixels

            # Show with OpenCV
            cv2.imshow("IC4 Mono8 Live", raw)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

        # ─────────────────────────────────────────────────────────────────────────
        # 8) Stop streaming and clean up
        grabber.stream_stop()
        cv2.destroyAllWindows()

    finally:
        # Always exit the IC4 library before quitting
        ic4.Library.exit()


if __name__ == "__main__":
    main()