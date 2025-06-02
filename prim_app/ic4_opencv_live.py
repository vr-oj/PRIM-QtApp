# File: ic4_opencv_live.py
import cv2
import numpy as np
import imagingcontrol4 as ic4
import sys

def main():
    # 1) Initialize the IC 4 library
    ic4.Library.init(api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR)

    # 2) Enumerate and pick the first connected camera
    device_list = ic4.DeviceEnum.devices()
    if not device_list:
        print("No IC 4 camera found.")
        ic4.Library.exit()
        sys.exit(1)

    dev_info = device_list[0]
    print(f"Found camera: {dev_info.model_name} (SN {dev_info.serial})")

    # 3) Open the Grabber, switch to Continuous acquisition if available
    grabber = ic4.Grabber()
    try:
        grabber.device_open(dev_info)
    except ic4.IC4Exception as e:
        print(f"ERROR: could not open camera: {e}")
        ic4.Library.exit()
        sys.exit(1)

    # If there is an “AcquisitionMode” enumeration, force it to “Continuous”
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

    # 4) Pick a PixelFormat entry. We will use the first one that works.
    #    In ic4-examples it is called "PixelFormat", and acceptable entries usually include: Mono8, Mono10p, BGRa8, etc.
    pf_node = grabber.device_property_map.find_enumeration("PixelFormat")
    if pf_node is None:
        print("No PixelFormat enumeration found on this camera.")
        grabber.device_close()
        ic4.Library.exit()
        sys.exit(1)

    # Try to set PixelFormat = "BGRa8"
    # (You can also iterate through pf_node.entries if you need to find a working one.)
    available_pf_names = [e.name for e in pf_node.entries]
    if "BGRa8" in available_pf_names:
        pf_node.value = "BGRa8"
        print("Using PixelFormat = BGRa8")
    else:
        # fall back to whatever the camera reports first
        pf_node.value = available_pf_names[0]
        print(f"Using PixelFormat = {available_pf_names[0]}")

    # 5) Create a QueueSink that requests exactly BGRa8 output buffers (1 buffer).
    #    max_output_buffers=1 means we always drop older frames if we can't keep up.
    sink = ic4.QueueSink(
        formats=[ic4.PixelFormat.BGRa8],
        max_output_buffers=1
    )

    # 6) Hook up the sink and start streaming
    grabber.stream_setup(sink)
    try:
        grabber.stream_start()
    except ic4.IC4Exception as e:
        print(f"ERROR: could not start stream: {e}")
        grabber.device_close()
        ic4.Library.exit()
        sys.exit(1)

    # 7) Main loop: pop each new buffer, convert to NumPy, display via OpenCV
    window_name = f"IC 4 Live View: {dev_info.model_name}"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    print("Press 'q' in the OpenCV window to quit.")
    while True:
        try:
            # time-out of 1000 ms → if no frame, we loop and check for 'q'
            buf = sink.pop_output_buffer(timeout=1000)
        except ic4.IC4Exception as e:
            # Could be a timeout or device‐lost
            print(f"Grab error (pop_output_buffer): {e}")
            break

        # buf is an ImageBuffer – wrap it as a NumPy array.  
        # numpy_wrap() returns a (height × stride) uint8 array, so we can slice off any padding.
        arr = buf.numpy_wrap()

        # The buffer’s “stride” is the number of bytes per row.
        # We know each pixel is 3 bytes (B, G, R) for BGRa8 → so stride = width × 3
        # Actually, for BGRa8, each pixel is 4 bytes (B,G,R,alpha), but numpy_wrap() will give a 
        # (height × (buf.stride)) buffer, so we need to reshape and drop the alpha channel.  
        height = buf.height
        stride = buf.stride  # bytes per row = width × 4
        width = buf.width

        # Reshape into (height, stride) then drop alpha column:
        raw2d = np.frombuffer(arr, dtype=np.uint8).reshape((height, stride))
        bgr4 = raw2d.reshape((height, width, 4))     # BGRA
        bgr3 = bgr4[:, :, :3]                        # drop alpha → BGR

        # Show with OpenCV
        cv2.imshow(window_name, bgr3)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    # 8) Cleanup
    print("Stopping stream and closing camera...")
    try:
        grabber.stream_stop()
    except Exception:
        pass
    grabber.device_close()
    ic4.Library.exit()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()