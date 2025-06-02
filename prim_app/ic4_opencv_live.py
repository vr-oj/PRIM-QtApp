# File: ic4_opencv_live.py

import sys
import cv2
import numpy as np
import imagingcontrol4 as ic4

# ─── A tiny “dummy” listener so QueueSink doesn’t try to call methods on None ─────────────────
class _DummyListener(ic4.QueueSinkListener):
    def sink_connected(self, sink: ic4.QueueSink, image_type: ic4.ImageType, min_buffers_required: int) -> bool:
        # We don’t need to allocate custom buffers, so just return True to accept the default
        return True

    def frames_queued(self, sink: ic4.QueueSink):
        # We’re pulling frames synchronously via pop_output_buffer(), 
        # so no need to do anything here.
        pass

    def sink_disconnected(self, sink: ic4.QueueSink):
        # Nothing special to do on disconnect
        pass


def main():
    # ─── 1) Initialize IC4 ─────────────────────────────────────────────────────
    ic4.Library.init(api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR)

    # ─── 2) Enumerate and pick the first camera ────────────────────────────────
    device_list = ic4.DeviceEnum.devices()
    if not device_list:
        print("No IC4 camera found.")
        ic4.Library.exit()
        sys.exit(1)

    dev_info = device_list[0]
    print(f"Found camera: {dev_info.model_name} (SN {dev_info.serial})")

    # ─── 3) Open grabber and set “Continuous” mode if available ────────────────
    grabber = ic4.Grabber()
    try:
        grabber.device_open(dev_info)
    except ic4.IC4Exception as e:
        print(f"ERROR: could not open camera: {e}")
        ic4.Library.exit()
        sys.exit(1)

    # Force “Continuous” if present
    try:
        acq = grabber.device_property_map.find_enumeration("AcquisitionMode")
        if acq:
            names = [e.name for e in acq.entries]
            if "Continuous" in names:
                acq.value = "Continuous"
            else:
                acq.value = names[0]
    except Exception:
        pass

    # ─── 4) Pick a PixelFormat (prefer BGRa8) ─────────────────────────────────
    pf_node = grabber.device_property_map.find_enumeration("PixelFormat")
    if pf_node is None:
        print("No PixelFormat enumeration found on this camera.")
        grabber.device_close()
        ic4.Library.exit()
        sys.exit(1)

    available_pf = [e.name for e in pf_node.entries]
    if "BGRa8" in available_pf:
        pf_node.value = "BGRa8"
        chosen_pf = "BGRa8"
    else:
        chosen_pf = available_pf[0]
        pf_node.value = chosen_pf

    print(f"Using PixelFormat = {chosen_pf}")

    # ─── 5) Create a QueueSink (with our dummy listener) ────────────────────────
    listener = _DummyListener()
    sink = ic4.QueueSink(
        listener,
        [ic4.PixelFormat.BGRa8],   # request BGRa8 (RGBA, 4 bytes/pixel) if possible
        max_output_buffers=1
    )

    # ─── 6) Tell the grabber to start streaming into that sink ──────────────────
    grabber.stream_setup(sink)
    # (Do NOT call grabber.stream_start(); stream_setup() is sufficient in this API.)

    # ─── 7) OpenCV window setup ────────────────────────────────────────────────
    window_name = f"IC4 Live View: {dev_info.model_name} [{chosen_pf}]"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    print("Press 'q' in the OpenCV window to quit.")
    while True:
        try:
            buf = sink.pop_output_buffer(timeout=1000)  # wait up to 1 s
        except ic4.IC4Exception as e:
            print(f"Grab error (pop_output_buffer): {e}")
            break

        # ─── 8) Convert the ImageBuffer → NumPy → OpenCV image ────────────────────
        height = buf.height
        width  = buf.width
        stride = buf.stride  # bytes per row

        raw = buf.numpy_wrap()  # 1D uint8 buffer of length (height * stride)

        # If stride == width, we got a Mono8 image (1 byte/pixel). Show as grayscale.
        if stride == width:
            gray2d = np.frombuffer(raw, dtype=np.uint8).reshape((height, stride))
            cv2.imshow(window_name, gray2d)

        # Otherwise, stride == width*4 → BGRA image → reshape & drop alpha
        else:
            arr2d = np.frombuffer(raw, dtype=np.uint8).reshape((height, stride))
            bgra  = arr2d.reshape((height, width, 4))    # BGRA ordering
            bgr   = bgra[:, :, :3]                       # drop alpha
            cv2.imshow(window_name, bgr)

        # Exit if user presses 'q'
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    # ─── 9) Clean up ───────────────────────────────────────────────────────────
    print("Stopping stream and closing camera…")
    try:
        grabber.stream_stop()
    except Exception:
        pass

    grabber.device_close()
    ic4.Library.exit()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()