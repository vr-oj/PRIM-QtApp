# File: grab_one_frame.py

import time
import imagingcontrol4 as ic4
import numpy as np
import cv2


class MinimalListener(ic4.QueueSinkListener):
    def frames_queued(self, sink, *args):
        pass

    def sink_connected(self, sink, *args):
        # Return True so the sink actually attaches
        return True


def main():
    # 1) Initialize the IC4 library
    try:
        ic4.Library.init()
    except ic4.IC4Exception as e:
        print("Library.init() failed:", e)
        return

    # 2) Enumerate devices
    try:
        devices = ic4.DeviceEnum.devices()
    except ic4.IC4Exception as e:
        print("DeviceEnum.devices() failed:", e)
        return

    if not devices:
        print("No IC4 cameras found.")
        return

    info = devices[0]
    print(f"Opening camera: {info.model_name}")

    # 3) Open the Grabber
    try:
        grabber = ic4.Grabber()
        grabber.device_open(info)
    except ic4.IC4Exception as e:
        print("Failed to open camera:", e)
        return

    pm = grabber.device_property_map

    # 4) Force PixelFormat → Mono8
    try:
        pi = pm.find_enumeration(ic4.PropId.PIXEL_FORMAT)
        if "Mono8" in pi.valid_value_strings:
            pi.value_string = "Mono8"
            print("Set PIXEL_FORMAT to Mono8")
        else:
            print(
                "Mono8 not supported! Valid PixelFormat options:",
                pi.valid_value_strings,
            )
            grabber.device_close()
            return
    except ic4.IC4Exception as e:
        print("Could not set PIXEL_FORMAT:", e)
        grabber.device_close()
        return

    # 5) Turn off auto‐exposure if available
    try:
        prop_auto = pm.find_boolean(ic4.PropId.EXPOSURE_AUTO)
        prop_auto.value = False
    except ic4.IC4Exception:
        pass

    # 6) Attach a QueueSink, but do NOT start acquisition yet
    listener = MinimalListener()
    sink = ic4.QueueSink(listener)
    grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.NONE)

    # 7) Pre‐allocate and queue 5 buffers BEFORE acquisition_start()
    sink.alloc_and_queue_buffers(5)

    # 8) Explicitly start acquisition
    try:
        grabber.acquisition_start()
    except ic4.IC4Exception as e:
        print("acquisition_start() failed:", e)
        grabber.device_close()
        return

    # 9) Pop exactly one buffer (with a 5 s timeout)
    buf = None
    start = time.time()
    while time.time() - start < 5.0:
        try:
            buf = sink.try_pop_output_buffer()
        except ic4.IC4Exception as e:
            print("Error popping buffer:", e)
            break
        if buf is not None:
            break
        time.sleep(0.001)

    if buf is None:
        print("Timed out waiting for a frame.")
    else:
        # 10) Convert the ImageBuffer to a NumPy array (Mono8 → uint8)
        arr = buf.numpy_wrap()
        img8 = np.array(arr, copy=False)

        # 11) Display in OpenCV
        cv2.imshow("Mono8 Frame", img8)
        cv2.waitKey(0)
        cv2.destroyAllWindows()

        try:
            buf.release()
        except:
            pass

    # 12) Cleanup
    try:
        grabber.acquisition_stop()
    except:
        pass
    grabber.device_close()


if __name__ == "__main__":
    main()
