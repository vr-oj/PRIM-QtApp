# ic4_test_basic.py (streamlined)
import imagingcontrol4 as ic4
import cv2
import time


class DummySinkListener:
    def sink_connected(self, sink, pixel_format, min_buffers_required):
        return True

    def sink_disconnected(self, sink):
        pass


def main():
    ic4.Library.init()
    devices = ic4.DeviceEnum.devices()
    if not devices:
        print("No devices!")
        ic4.Library.exit()
        return

    grabber = ic4.Grabber()
    grabber.device_open(devices[0])
    print("Grabber opened.")

    # Set Continuous, Mono8, 640×480 (same as before)…
    try:
        acq_node = grabber.device_property_map.find_enumeration(
            ic4.PropId.ACQUISITION_MODE
        )
        if acq_node and "Continuous" in [e.name for e in acq_node.entries]:
            acq_node.value = "Continuous"
    except:
        pass

    try:
        pf_node = grabber.device_property_map.find_enumeration(ic4.PropId.PIXEL_FORMAT)
        if pf_node and "Mono8" in [e.name for e in pf_node.entries if e.is_available]:
            pf_node.value = "Mono8"
    except:
        pass

    try:
        w_node = grabber.device_property_map.find_integer(ic4.PropId.WIDTH)
        h_node = grabber.device_property_map.find_integer(ic4.PropId.HEIGHT)
        if w_node and h_node:
            w_node.value = min(w_node.value, 640)
            h_node.value = min(h_node.value, 480)
    except:
        pass

    listener = DummySinkListener()
    sink = ic4.QueueSink(listener, [ic4.PixelFormat.Mono8], max_output_buffers=1)

    # This single call already starts acquisition:
    grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)
    print("StreamSetup complete; acquisition is already active.")

    time.sleep(1.0)  # let the camera fill buffers

    cv2.namedWindow("Frame", cv2.WINDOW_NORMAL)
    for _ in range(5):
        try:
            buf = sink.pop_output_buffer()  # blocking
            arr = buf.numpy_wrap()
            cv2.imshow("Frame", arr)
            cv2.waitKey(200)
            sink.queue_buffer(buf)
        except ic4.IC4Exception as e:
            print("No frame or error:", e)
            time.sleep(0.1)

    # Cleanup
    grabber.acquisition_stop()
    grabber.stream_stop()
    grabber.device_close()
    cv2.destroyAllWindows()
    del sink, grabber
    ic4.Library.exit()
    print("Done.")
