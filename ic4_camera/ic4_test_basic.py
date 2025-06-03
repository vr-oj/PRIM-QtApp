# ic4_test_basic.py
import imagingcontrol4 as ic4
import numpy as np
import cv2
import time


class DummySinkListener:
    def sink_connected(self, sink, pixel_format, min_buffers_required):
        return True

    def sink_disconnected(self, sink):
        pass


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

    # 4) Set AcquisitionMode = Continuous (if available)
    try:
        acq_node = grabber.device_property_map.find_enumeration(
            ic4.PropId.ACQUISITION_MODE
        )
        if acq_node and "Continuous" in [entry.name for entry in acq_node.entries]:
            acq_node.value = "Continuous"
            print("AcquisitionMode set to Continuous.")
    except Exception as e:
        print("Warning: could not set AcquisitionMode →", e)

    # 5) Pick a pixel format: try Mono8, else BGR8, else camera default
    try:
        pf_node = grabber.device_property_map.find_enumeration(ic4.PropId.PIXEL_FORMAT)
        if pf_node:
            available = [entry.name for entry in pf_node.entries if entry.is_available]
            if "Mono8" in available:
                pf_node.value = "Mono8"
                print("PixelFormat set to Mono8")
            elif "BGR8" in available:
                pf_node.value = "BGR8"
                print("Mono8 not available; using BGR8")
            else:
                pf_node.value = available[0]
                print(f"Using fallback pixel format {available[0]}")
    except Exception as e:
        print("Warning: could not set PixelFormat →", e)

    # 6) Clamp width/height to 640×480 (if supported)
    try:
        w_node = grabber.device_property_map.find_integer(ic4.PropId.WIDTH)
        h_node = grabber.device_property_map.find_integer(ic4.PropId.HEIGHT)
        if w_node and h_node:
            w_node.value = min(w_node.value, 640)
            h_node.value = min(h_node.value, 480)
            print(f"Requested W×H = {w_node.value}×{h_node.value}")
    except Exception as e:
        print("Warning: could not set resolution →", e)

    # 7) Create and attach DummySinkListener + QueueSink
    listener = DummySinkListener()
    sink = ic4.QueueSink(listener, [ic4.PixelFormat.Mono8], max_output_buffers=1)

    # 8) Start streaming
    try:
        grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)
        print("StreamSetup complete.")
        # Try to start acquisition, but ignore "already active" if it comes up
        try:
            grabber.acquisition_start()
            print("grabber.acquisition_start() called.")
        except ic4.IC4Exception as e:
            if e.error_code == ic4.ErrorCode.InvalidOperation:
                print("Note: acquisition was already active (ignored).")
            else:
                raise
    except Exception as e:
        print("❌ Failed to start stream:", e)
        grabber.device_close()
        ic4.Library.exit()
        return

    # 9) Give camera a moment to warm up
    time.sleep(1.0)

    # 10) Grab 5 frames (blocking pop) and display via OpenCV
    print("Grabbing 5 frames…")
    cv2.namedWindow("Frame", cv2.WINDOW_NORMAL)
    for i in range(5):
        try:
            buf = sink.pop_output_buffer()  # blocking
            arr = buf.numpy_wrap()  # Mono8 → (H,W) or BGR8 → (H,W,3)
            cv2.imshow("Frame", arr)
            cv2.waitKey(200)  # hold each frame for 200 ms
            sink.queue_buffer(buf)
        except ic4.IC4Exception as e:
            print("No frame yet or error:", e)
            time.sleep(0.1)

    # 11) Stop acquisition, stop stream, close device
    try:
        grabber.acquisition_stop()
    except Exception:
        pass  # ignore if it wasn't running
    grabber.stream_stop()
    grabber.device_close()
    cv2.destroyAllWindows()
    print("Streaming stopped, camera closed.")

    # 12) Explicitly delete objects before shutting down library
    del sink
    del grabber

    # 13) Shutdown library
    ic4.Library.exit()
    print("Library.exit() complete.")


if __name__ == "__main__":
    main()
