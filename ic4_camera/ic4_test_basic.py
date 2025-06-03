import imagingcontrol4 as ic4
import numpy as np
import cv2  # for quick display
import time


def main():
    # 1) Init the IC4 library
    ic4.Library.init(api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR)
    print("Library.init() succeeded.")

    # 2) Enumerate devices
    devices = ic4.DeviceEnum.devices()
    if not devices:
        print("❌ No IC4 devices found!")
        ic4.Library.exit()
        return

    dev_info = devices[0]
    print(f"Found device: {dev_info.model_name}, S/N: {dev_info.serial}")

    # 3) Open the grabber
    grabber = ic4.Grabber()
    grabber.device_open(dev_info)
    print("Grabber opened successfully.")

    # 4) Set Continuous mode if available
    acq_node = grabber.device_property_map.find_enumeration(ic4.PropId.ACQUISITION_MODE)
    if acq_node:
        modes = [entry.name for entry in acq_node.entries]
        if "Continuous" in modes:
            acq_node.value = "Continuous"
        else:
            acq_node.value = modes[0]
    print("AcquisitionMode set to Continuous.")

    # 5) Pick a common PixelFormat—Mono8 if it’s monochrome
    pf_node = grabber.device_property_map.find_enumeration(ic4.PropId.PIXEL_FORMAT)
    if pf_node and "Mono8" in [e.name for e in pf_node.entries]:
        pf_node.value = "Mono8"
        print("PixelFormat set to Mono8")

    # 6) Try setting a small resolution (to speed up)
    w_node = grabber.device_property_map.find_integer(ic4.PropId.WIDTH)
    h_node = grabber.device_property_map.find_integer(ic4.PropId.HEIGHT)
    if w_node and h_node:
        w_node.value = min(w_node.value, 640)
        h_node.value = min(h_node.value, 480)
        print(f"Requested W×H = {w_node.value}×{h_node.value}")

    # 7) Set up a sink that delivers BGR8 or Mono8
    #    For demo, we’ll ask for Mono8 so converting to OpenCV is easy.
    sink = ic4.QueueSink(None, [ic4.PixelFormat.Mono8], max_output_buffers=1)
    grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)
    print("Streaming started. Grabbing 5 frames...")

    for i in range(5):
        time.sleep(0.1)
        try:
            buf = sink.pop_output_buffer(timeout=1000)  # 1s timeout
            arr = buf.numpy_wrap()  # NumPy array (h×w) for Mono8
            # Show with OpenCV
            cv2.imshow("Frame (Mono8)", arr)
            cv2.waitKey(100)
            sink.queue_buffer(buf)  # Requeue if needed
        except ic4.IC4Exception as e:
            print("No frame yet or error:", e)
    grabber.stream_stop()
    grabber.device_close()
    cv2.destroyAllWindows()
    print("Streaming stopped, camera closed.")

    ic4.Library.exit()
    print("Library.exit() complete.")


if __name__ == "__main__":
    main()
