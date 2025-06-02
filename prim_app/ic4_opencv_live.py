# File: ic4_opencv_live_fixed.py

import cv2
import numpy as np
import imagingcontrol4 as ic4

class _DummyListener(ic4.QueueSinkListener):
    """
    A minimal QueueSinkListener that allocates exactly
    as many buffers as the driver says it needs (min_buffers_required).
    """
    def __init__(self):
        super().__init__()

    def sink_connected(
        self,
        sink: ic4.QueueSink,
        image_type: ic4.ImageType,
        min_buffers_required: int,
    ) -> bool:
        # Allocate exactly min_buffers_required buffers (or more if you like).
        sink.alloc_and_queue_buffers(min_buffers_required)
        return True

    def sink_disconnected(self, sink: ic4.QueueSink) -> None:
        # Called when the sink is torn down; nothing special to do.
        pass

    def frames_queued(self, sink: ic4.QueueSink) -> None:
        # We will manually pop buffers in main(), so no work here.
        pass


def main():
    # ───────────────────────────────────────────────────────────────────────────
    # 1) Initialize IC4 (always match with Library.exit() at the end)
    ic4.Library.init(api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR)

    try:
        # ─────────────────────────────────────────────────────────────────────────
        # 2) Enumerate cameras
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
            print("⚠️ Warning: no PixelFormat node found; continuing with driver default.")

        # ─────────────────────────────────────────────────────────────────────────
        # 5) Build a QueueSink + our dummy listener.  Pass a list of PixelFormat enums.
        listener = _DummyListener()
        sink = ic4.QueueSink(listener, [ic4.PixelFormat.Mono8], max_output_buffers=10)

        # ─────────────────────────────────────────────────────────────────────────
        # 6) Start streaming.  stream_setup() already begins acquisition.
        grabber.stream_setup(sink)
        print("Streaming started. Press 'q' to quit.\n")

        # ─────────────────────────────────────────────────────────────────────────
        # 7) Main loop: pop buffers and display with OpenCV
        while True:
            try:
                buf = sink.pop_output_buffer()
            except ic4.IC4Exception as e:
                # If there really is no data yet, we get ErrorCode.NoData → loop again
                if e.code == ic4.Error.NoData:
                    continue
                print(f"Grab error: {e}")
                break

            # Because we asked for Mono8, buf.numpy_wrap() returns a 2D uint8 array
            raw = buf.numpy_wrap()   # shape = (height, width), dtype=uint8
            h = buf.height
            w = buf.width

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