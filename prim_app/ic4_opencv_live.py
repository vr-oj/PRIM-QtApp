import imagingcontrol4 as ic4
import cv2
import numpy as np

def main():
    ic4.Library.init(api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR)

    # 1) Find and open the first camera
    dev_list = ic4.DeviceEnum.devices()
    if not dev_list:
        print("No camera found.")
        return

    dev_info = dev_list[0]
    print(f"Found camera: {dev_info.model_name} (SN {dev_info.serial})")

    grabber = ic4.Grabber()
    grabber.device_open(dev_info)

    # 2) Force CS “Continuous” mode if you like:
    pm = grabber.device_property_map
    acq_node = pm.find_enumeration("AcquisitionMode")
    if acq_node:
        names = [e.name for e in acq_node.entries]
        acq_node.value = "Continuous" if "Continuous" in names else names[0]

    # 3) Pick a PixelFormat that actually works (Mono8 is usually supported)
    pf_node = pm.find_enumeration("PixelFormat")
    if pf_node:
        pf_node.value = "Mono8"  # or any name from [e.name for e in pf_node.entries]

    # 4) Create a QueueSink (no custom listener, just retrieve frames manually)
    sink = ic4.QueueSink(None, [ic4.PixelFormat.Mono8], max_output_buffers=6)

    # 5) Start the live-stream
    grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)
    print("Streaming started. Press 'q' to quit.")

    try:
        while True:
            try:
                buf = sink.pop_output_buffer()
            except ic4.IC4Exception as e:
                # If there’s simply no data yet, loop again
                if e.code == ic4.ErrorCode.NoData:
                    continue
                else:
                    raise

            # Now that we successfully got a buffer, pull out width/height/stride
            w = buf.width
            h = buf.height
            stride = buf.stride

            # raw_ptr is a ctypes pointer to the BGRA or Mono8 data
            raw_ptr = buf.get_buffer()

            # Build a NumPy view.  If Mono8, count = h * stride
            arr = np.frombuffer(raw_ptr, dtype=np.uint8, count=h * stride)
            arr = arr.reshape((h, stride))
            arr = arr[:, :w]            # drop any padding beyond width
            img = arr.copy()           # now 'img' is shape (h, w), dtype=uint8

            # Show with OpenCV
            cv2.imshow("IC4 → OpenCV", img)
            buf.release()  # must release or delete the buffer

            key = cv2.waitKey(1)
            if key == ord("q"):
                break

    finally:
        cv2.destroyAllWindows()
        grabber.stream_stop()
        grabber.device_close()
        ic4.Library.exit()


if __name__ == "__main__":
    main()