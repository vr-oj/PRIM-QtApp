# ic4_test_software_trigger.py
import imagingcontrol4 as ic4
import cv2
import time


class DummyListener:
    def sink_connected(self, sink, pf, min_bufs):
        return True

    def sink_disconnected(self, sink):
        pass


def main():
    # 1) Initialize IC4
    ic4.Library.init(api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR)
    print("Library.init() succeeded.")

    # 2) Open the first device
    devices = ic4.DeviceEnum.devices()
    if not devices:
        print("No IC4 devices found.")
        ic4.Library.exit()
        return
    dev = devices[0]
    grabber = ic4.Grabber()
    grabber.device_open(dev)
    print(f"Opened camera: {dev.model_name} (S/N {dev.serial})")

    # 3) Switch into Software-Trigger Mode (SingleFrame)
    try:
        # 3a) Turn TriggerMode = "On"
        trig_node = grabber.device_property_map.find_enumeration(
            ic4.PropId.TRIGGER_MODE
        )
        if trig_node and "On" in [e.name for e in trig_node.entries]:
            trig_node.value = "On"
            print("  → Set TriggerMode = On")
        else:
            print("  → Cannot find TriggerMode/On; aborting")
            raise RuntimeError("TriggerMode not available")

        # 3b) Set TriggerSource = "Software"
        src_node = grabber.device_property_map.find_enumeration(
            ic4.PropId.TRIGGER_SOURCE
        )
        if src_node and "Software" in [e.name for e in src_node.entries]:
            src_node.value = "Software"
            print("  → Set TriggerSource = Software")
        else:
            print("  → Cannot find TriggerSource/Software; aborting")
            raise RuntimeError("TriggerSource not available")

        # 3c) Ensure TriggerActivation = "RisingEdge" (usually default)
        act_node = grabber.device_property_map.find_enumeration(
            ic4.PropId.TRIGGER_ACTIVATION
        )
        if act_node and "RisingEdge" in [e.name for e in act_node.entries]:
            act_node.value = "RisingEdge"
            print("  → Set TriggerActivation = RisingEdge")
    except Exception as e:
        print("✗ Could not configure software trigger:", e)

    # 4) Set AcquisitionMode = SingleFrame (so each software trigger yields exactly one frame)
    try:
        acq_node = grabber.device_property_map.find_enumeration(
            ic4.PropId.ACQUISITION_MODE
        )
        if acq_node and "SingleFrame" in [e.name for e in acq_node.entries]:
            acq_node.value = "SingleFrame"
            print("  → Set AcquisitionMode = SingleFrame")
        else:
            print("  → Cannot find AcquisitionMode/SingleFrame; continuing anyway")
    except Exception as e:
        print("✗ Could not set AcquisitionMode:", e)

    # 5) Set PixelFormat = Mono8 and Resolution = 640×480
    try:
        pf_node = grabber.device_property_map.find_enumeration(ic4.PropId.PIXEL_FORMAT)
        available_pf = [e.name for e in pf_node.entries if e.is_available]
        if "Mono8" in available_pf:
            pf_node.value = "Mono8"
            print("  → Set PixelFormat = Mono8")
        else:
            print("  → Mono8 not available; using", available_pf[0])
            pf_node.value = available_pf[0]
    except Exception as e:
        print("✗ Could not set PixelFormat:", e)

    try:
        w_node = grabber.device_property_map.find_integer(ic4.PropId.WIDTH)
        h_node = grabber.device_property_map.find_integer(ic4.PropId.HEIGHT)
        if w_node and h_node:
            w_node.value = min(w_node.value, 640)
            h_node.value = min(h_node.value, 480)
            print(f"  → Resolution = {w_node.value}×{h_node.value}")
    except Exception as e:
        print("✗ Could not set resolution:", e)

    # 6) Create a QueueSink and attach our DummyListener
    listener = DummyListener()
    sink = ic4.QueueSink(listener, [ic4.PixelFormat.Mono8], max_output_buffers=1)
    print("  → QueueSink created.")

    # 7) Call stream_setup (no ACQUISITION_START here; SingleFrame mode relies on software trigger)
    grabber.stream_setup(sink)
    print("  → stream_setup() succeeded (waiting software triggers).")

    # 8) Wait a moment
    time.sleep(0.5)

    # 9) Issue 5 software triggers, one at a time
    print("  → Issuing 5 software triggers…")
    cv2.namedWindow("Frame", cv2.WINDOW_NORMAL)
    for i in range(5):
        try:
            # 9a) Fire software trigger (this makes the camera capture exactly one frame)
            grabber.trigger_software()
            # 9b) Pop the resulting buffer
            buf = sink.pop_output_buffer()  # blocking until that single frame arrives
            arr = buf.numpy_wrap()
            print(f"    → Got frame {i+1}, shape = {arr.shape}")
            cv2.imshow("Frame", arr)
            cv2.waitKey(200)  # display 200 ms
            sink.queue_buffer(buf)
        except ic4.IC4Exception as e:
            print(f"    ✗ Frame {i+1} pop_output_buffer error:", e)
            time.sleep(0.1)

    # 10) Clean up
    grabber.stream_stop()
    grabber.device_close()
    cv2.destroyAllWindows()
    del sink, grabber
    ic4.Library.exit()
    print("Done. Exiting.")


if __name__ == "__main__":
    main()
