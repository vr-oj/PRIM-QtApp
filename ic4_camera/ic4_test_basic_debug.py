# ic4_test_basic_debug2.py
import imagingcontrol4 as ic4
import cv2
import time
import sys


class DummySinkListener:
    def sink_connected(self, sink, pixel_format, min_buffers_required):
        print("  [Listener] sink_connected called.")
        return True

    def sink_disconnected(self, sink):
        print("  [Listener] sink_disconnected called.")
        pass


def main():
    print("1) Entered main()")

    # 1) Init the IC4 library
    try:
        print("2) Calling Library.init()")
        ic4.Library.init(
            api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR
        )
        print("   → Library.init() succeeded.")
    except Exception as e:
        print("   ✗ Library.init() raised exception:", e)
        return

    # 2) Enumerate devices
    try:
        print("3) Calling DeviceEnum.devices()")
        devices = ic4.DeviceEnum.devices()
        print(f"   → Found {len(devices)} device(s).")
        if not devices:
            print("   ✗ No IC4 devices found!")
            ic4.Library.exit()
            return
    except Exception as e:
        print("   ✗ DeviceEnum.devices() raised exception:", e)
        ic4.Library.exit()
        return

    # 3) Open the grabber
    try:
        dev_info = devices[0]
        print(f"4) Using device: {dev_info.model_name} (S/N {dev_info.serial})")
        grabber = ic4.Grabber()
        print("   → Created Grabber() instance.")
        grabber.device_open(dev_info)
        print("   → grabber.device_open() succeeded.")
    except Exception as e:
        print("   ✗ grabber.device_open() raised exception:", e)
        ic4.Library.exit()
        return

    # 4) Set AcquisitionMode = Continuous (if available)
    try:
        print("5) Attempting to set AcquisitionMode to Continuous")
        acq_node = grabber.device_property_map.find_enumeration(
            ic4.PropId.ACQUISITION_MODE
        )
        if acq_node:
            available = [entry.name for entry in acq_node.entries]
            print("   → Available AcquisitionMode entries:", available)
            if "Continuous" in available:
                acq_node.value = "Continuous"
                print("   → AcquisitionMode set to Continuous.")
            else:
                print("   → 'Continuous' not in entries; skipping set.")
        else:
            print("   → No AcquisitionMode node found; skipping.")
    except Exception as e:
        print("   ✗ Setting AcquisitionMode raised exception:", e)

    # 5) Pick a pixel format: try Mono8, else BGR8, else camera default
    try:
        print("6) Attempting to set PixelFormat")
        pf_node = grabber.device_property_map.find_enumeration(ic4.PropId.PIXEL_FORMAT)
        if pf_node:
            available_pf = [
                entry.name for entry in pf_node.entries if entry.is_available
            ]
            print("   → Available PixelFormat entries:", available_pf)
            if "Mono8" in available_pf:
                pf_node.value = "Mono8"
                print("   → PixelFormat set to Mono8")
            elif "BGR8" in available_pf:
                pf_node.value = "BGR8"
                print("   → Mono8 not available; PixelFormat set to BGR8")
            else:
                pf_node.value = available_pf[0]
                print(f"   → Fallback PixelFormat: {available_pf[0]}")
        else:
            print("   → No PixelFormat node found; skipping.")
    except Exception as e:
        print("   ✗ Setting PixelFormat raised exception:", e)

    # 6) Clamp width/height to 640×480 (if supported)
    try:
        print("7) Attempting to set width/height")
        w_node = grabber.device_property_map.find_integer(ic4.PropId.WIDTH)
        h_node = grabber.device_property_map.find_integer(ic4.PropId.HEIGHT)
        if w_node and h_node:
            print(f"   → Current width×height = {w_node.value}×{h_node.value}")
            w_node.value = min(w_node.value, 640)
            h_node.value = min(h_node.value, 480)
            print(f"   → Requested width×height = {w_node.value}×{h_node.value}")
        else:
            print("   → WIDTH or HEIGHT node not found; skipping.")
    except Exception as e:
        print("   ✗ Setting width/height raised exception:", e)

    # 7) Create and attach DummySinkListener + QueueSink
    try:
        print("8) Creating DummySinkListener and QueueSink")
        listener = DummySinkListener()
        sink = ic4.QueueSink(listener, [ic4.PixelFormat.Mono8], max_output_buffers=1)
        print("   → QueueSink created.")
    except Exception as e:
        print("   ✗ Creating QueueSink raised exception:", e)
        grabber.device_close()
        ic4.Library.exit()
        return

    # 8) Start streaming (stream_setup only; no ACQUISITION_START here)
    try:
        print("9) Calling grabber.stream_setup(sink, default)")
        grabber.stream_setup(sink)  # no ACQUISITION_START
        print("   → stream_setup() succeeded (acquisition not started yet).")
    except Exception as e:
        print("   ✗ stream_setup() raised exception:", e)
        try:
            grabber.device_close()
        except:
            pass
        ic4.Library.exit()
        return

    # 9) Now explicitly start acquisition
    try:
        print("10) Calling grabber.acquisition_start()")
        grabber.acquisition_start()
        print("   → grabber.acquisition_start() succeeded.")
    except Exception as e:
        print("   ✗ grabber.acquisition_start() raised exception:", e)
        # If acquisition is already active, you can ignore it,
        # but if it’s any other error, bail out:
        if isinstance(e, ic4.IC4Exception):
            print("   → Acquisition may already be active, continuing.")
        else:
            try:
                grabber.device_close()
            except:
                pass
            ic4.Library.exit()
            return

    # 10) Give camera extra warm-up time
    print("11) Sleeping for 2 seconds so camera can warm up buffers…")
    time.sleep(2.0)

    # 11) Grab 5 frames (blocking pop) and display via OpenCV
    print("12) Attempting to pop 5 frames now…")
    cv2.namedWindow("Frame", cv2.WINDOW_NORMAL)
    for idx in range(5):
        try:
            print(f"    → pop_output_buffer() for frame {idx+1}")
            buf = sink.pop_output_buffer()  # blocking
            arr = buf.numpy_wrap()
            print(f"    → Received buffer, shape = {arr.shape}")
            cv2.imshow("Frame", arr)
            cv2.waitKey(200)
            sink.queue_buffer(buf)
        except ic4.IC4Exception as e:
            print(f"    ✗ Frame {idx+1} pop_output_buffer() error:", e)
            time.sleep(0.1)
        except Exception as e:
            print(f"    ✗ Unexpected exception while popping frame {idx+1}:", e)
            time.sleep(0.1)

    # 12) Stop acquisition, stop stream, close device
    print("13) Stopping acquisition/stream, closing device…")
    try:
        grabber.acquisition_stop()
        print("    → grabber.acquisition_stop() succeeded.")
    except Exception as e:
        print("    ✗ grabber.acquisition_stop() raised exception:", e)
    try:
        grabber.stream_stop()
        print("    → grabber.stream_stop() succeeded.")
    except Exception as e:
        print("    ✗ grabber.stream_stop() raised exception:", e)
    try:
        grabber.device_close()
        print("    → grabber.device_close() succeeded.")
    except Exception as e:
        print("    ✗ grabber.device_close() raised exception:", e)
    cv2.destroyAllWindows()
    print("    → cv2 windows destroyed.")

    # 13) Clean up objects before exit
    print("14) Deleting sink and grabber…")
    try:
        del sink
        del grabber
        print("    → sink and grabber deleted.")
    except Exception as e:
        print("    ✗ Deleting sink/grabber raised exception:", e)

    # 14) Shutdown library
    print("15) Calling Library.exit()")
    try:
        ic4.Library.exit()
        print("    → Library.exit() succeeded.")
    except Exception as e:
        print("    ✗ Library.exit() raised exception:", e)

    print("=== End of main() ===")


if __name__ == "__main__":
    print("=== Starting ic4_test_basic_debug2.py ===")
    main()
    print("=== Exiting ic4_test_basic_debug2.py ===")
    sys.exit(0)
