# ic4_test_free_run.py
import imagingcontrol4 as ic4
import cv2
import time


class DummyListener:
    def sink_connected(self, sink, pf, min_bufs):
        return True

    def sink_disconnected(self, sink):
        pass


def main():
    # 1) Init IC4
    ic4.Library.init(api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR)
    print("Library.init() succeeded.")

    # 2) Open first camera (DMK 33UP5000)
    devices = ic4.DeviceEnum.devices()
    if not devices:
        print("No IC4 devices found.")
        ic4.Library.exit()
        return
    dev = devices[0]
    grabber = ic4.Grabber()
    grabber.device_open(dev)
    print(f"Opened camera: {dev.model_name} (S/N {dev.serial})")

    # 3) Disable hardware trigger
    trigger_node = grabber.device_property_map.find_enumeration(ic4.PropId.TRIGGER_MODE)
    if trigger_node:
        choices = [entry.name for entry in trigger_node.entries]
        print("  → TriggerMode options:", choices)
        if "Off" in choices:
            trigger_node.value = "Off"
            print("  → Set TriggerMode = Off")
        else:
            print("  → 'Off' not available; skipping")
    else:
        print("  → No TriggerMode node found; assuming free-run default")

    # 4) Set Continuous, Mono8, 640×480
    acq_node = grabber.device_property_map.find_enumeration(ic4.PropId.ACQUISITION_MODE)
    if acq_node and "Continuous" in [e.name for e in acq_node.entries]:
        acq_node.value = "Continuous"
        print("  → Set AcquisitionMode = Continuous")

    pf_node = grabber.device_property_map.find_enumeration(ic4.PropId.PIXEL_FORMAT)
    if pf_node and "Mono8" in [e.name for e in pf_node.entries if e.is_available]:
        pf_node.value = "Mono8"
        print("  → Set PixelFormat = Mono8")

    w_node = grabber.device_property_map.find_integer(ic4.PropId.WIDTH)
    h_node = grabber.device_property_map.find_integer(ic4.PropId.HEIGHT)
    if w_node and h_node:
        w_node.value = min(w_node.value, 640)
        h_node.value = min(h_node.value, 480)
        print(f"  → Set resolution = {w_node.value}×{h_node.value}")

    # 5) Create sink with dummy listener
    listener = DummyListener()
    sink = ic4.QueueSink(listener, [ic4.PixelFormat.Mono8], max_output_buffers=1)
    print("  → QueueSink created.")

    # 6) Start streaming (and implicitly acquisition)
    grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)
    print("  → stream_setup() succeeded; acquisition active.")

    # 7) Warm up for 2 s
    print("  → Sleeping 2 s for warm-up…")
    time.sleep(2.0)

    # 8) Grab 5 frames
    print("  → Attempting to grab 5 frames:")
    cv2.namedWindow("Frame", cv2.WINDOW_NORMAL)
    for i in range(5):
        try:
            buf = sink.pop_output_buffer()  # blocking
            arr = buf.numpy_wrap()
            print(f"    → Got frame {i+1}, shape={arr.shape}")
            cv2.imshow("Frame", arr)
            cv2.waitKey(200)
            sink.queue_buffer(buf)
        except ic4.IC4Exception as e:
            print(f"    ✗ Frame {i+1} NoData/error:", e)
            time.sleep(0.1)

    # 9) Clean up
    grabber.acquisition_stop()
    grabber.stream_stop()
    grabber.device_close()
    cv2.destroyAllWindows()
    del sink, grabber

    ic4.Library.exit()
    print("Done. Exiting.")


if __name__ == "__main__":
    main()
