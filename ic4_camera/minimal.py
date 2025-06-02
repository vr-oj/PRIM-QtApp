# File: minimal.py

import time
import imagingcontrol4 as ic4
import numpy as np
import cv2


class MinimalListener(ic4.QueueSinkListener):
    def frames_queued(self, sink, *args):
        pass

    def sink_connected(self, sink, *args):
        # Must return True to allow the sink to attach and start streaming
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

    # 4) Query and set ExposureTime via find_float()
    try:
        prop_exp = pm.find_float(ic4.PropId.EXPOSURE_TIME)
        print("Current ExposureTime (µs):", prop_exp.value)
        # Optionally set it to the same or a new value, e.g.:
        # prop_exp.value = 10000.0
    except ic4.IC4Exception as exc:
        print("Could not find/set ExposureTime:", exc)

    # 5) Turn off auto‐exposure (if present)
    try:
        prop_auto = pm.find_boolean(ic4.PropId.EXPOSURE_AUTO)
        prop_auto.value = False
    except ic4.IC4Exception:
        pass

    # 6) Attach a QueueSink and start acquisition
    listener = MinimalListener()
    sink = ic4.QueueSink(listener)
    try:
        grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)
    except ic4.IC4Exception as e:
        print("stream_setup failed (sink_connected probably returned false):", e)
        grabber.device_close()
        return

    # 7) Pre‐allocate a few buffers
    sink.alloc_and_queue_buffers(5)

    # 8) Pop exactly one buffer (with a timeout)
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
        # 9) Convert the ImageBuffer to a NumPy array
        arr = buf.numpy_wrap()
        np_img = np.array(arr, copy=False)

        # 10) Down‐shift 16‐bit → 8‐bit if needed
        if np_img.dtype == np.uint16:
            img8 = (np_img >> 8).astype(np.uint8)
        else:
            img8 = np_img

        # 11) If multi‐channel, assume BGR8; otherwise grayscale
        if img8.ndim == 3 and img8.shape[2] == 3:
            display = img8
        else:
            display = img8 if img8.ndim == 2 else img8[:, :, 0]

        cv2.imshow("One Frame", display)
        cv2.waitKey(0)
        cv2.destroyAllWindows()

        # 12) Release the buffer so the sink can reuse it
        try:
            buf.release()
        except:
            pass

    # 13) Clean up
    try:
        grabber.acquisition_stop()
    except:
        pass
    grabber.device_close()


if __name__ == "__main__":
    main()
