# File: ic4_opencv_live.py
import sys
import cv2
import numpy as np
import imagingcontrol4 as ic4

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

    # ─── 3) Open grabber and set Continuous mode if available ─────────────────
    grabber = ic4.Grabber()
    try:
        grabber.device_open(dev_info)
    except ic4.IC4Exception as e:
        print(f"ERROR: could not open camera: {e}")
        ic4.Library.exit()
        sys.exit(1)

    # Try to force “Continuous” acquisition if that enum exists
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
        # fall back to the first reported format (e.g. “Mono8”)
        chosen_pf = available_pf[0]
        pf_node.value = chosen_pf

    print(f"Using PixelFormat = {chosen_pf}")

    # ─── 5) Create a QueueSink (no listener, request exactly BGRa8 so we get 4‐byte RGBA)
    #      If the camera is actually Mono8 only, it will output single‐channel buffers
    sink = ic4.QueueSink(
        None,                  # no listener callback
        [ic4.PixelFormat.BGRa8],  # request BGRa8 (4 bytes/pixel) if possible
        max_output_buffers=1
    )

    # ─── 6) Hook up the sink and start streaming ────────────────────────────────
    grabber.stream_setup(sink)
    try:
        grabber.stream_start()
    except ic4.IC4Exception as e:
        print(f"ERROR: could not start stream: {e}")
        grabber.device_close()
        ic4.Library.exit()
        sys.exit(1)

    # ─── 7) OpenCV window setup ────────────────────────────────────────────────
    window_name = f"IC4 Live View: {dev_info.model_name} [{chosen_pf}]"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    print("Press 'q' in the OpenCV window to quit.")
    while True:
        try:
            buf = sink.pop_output_buffer(timeout=1000)  # wait up to 1 s for a frame
        except ic4.IC4Exception as e:
            print(f"Grab error (pop_output_buffer): {e}")
            break

        # ─── 8) Convert buffer → NumPy → OpenCV image ─────────────────────────────
        # The ImageBuffer has attributes: width, height, stride, and a .numpy_wrap() method.
        height = buf.height
        width  = buf.width
        stride = buf.stride  # bytes per row

        raw = buf.numpy_wrap()  # returns a 1D uint8 buffer of length (height * stride)

        # If we requested BGRa8 but the camera only supports Mono8, we'll get a single‐channel
        # buffer where stride == width and raw is (height*width) bytes. Otherwise, stride == width*4.
        if stride == width:
            # Mono8 case: reshape into (height, width) and show grayscale
            gray2d = np.frombuffer(raw, dtype=np.uint8).reshape((height, stride))
            gray_img = gray2d  # shape = (height, width)
            cv2.imshow(window_name, gray_img)

        else:
            # BGRa8 case: reshape into (height, stride), then into (height, width, 4), drop alpha
            arr2d = np.frombuffer(raw, dtype=np.uint8).reshape((height, stride))
            bgra = arr2d.reshape((height, width, 4))  # BGRA
            bgr  = bgra[:, :, :3]                     # drop alpha
            cv2.imshow(window_name, bgr)

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