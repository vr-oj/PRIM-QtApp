# File: minimal.py

import time
import imagingcontrol4 as ic4
import numpy as np
import cv2


class MinimalListener(ic4.QueueSinkListener):
    def frames_queued(self, sink, *args):
        pass

    def sink_connected(self, sink, *args):
        pass


def main():
    # 1) Init library
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

    # 3) Open Grabber
    try:
        grabber = ic4.Grabber()
        grabber.device_open(info)
    except ic4.IC4Exception as e:
        print("Failed to open camera:", e)
        return

    pm = grabber.device_property_map

    # 4) Query and set ExposureTime (now using find_float)
    try:
        prop_exp = pm.find_float(ic4.PropId.EXPOSURE_TIME)
        print("Current ExposureTime (µs):", prop_exp.value)
        prop_exp.value = prop_exp.value  # leave unchanged or set a new float value
    except ic4.IC4Exception as exc:
        print("Could not find/set ExposureTime:", exc)

    # 5) (Optional) set ExposureAuto off if you want manual control (for some cameras):
    try:
        prop_auto = pm.find_boolean(ic4.PropId.EXPOSURE_AUTO)
        prop_auto.value = False
    except ic4.IC4Exception:
        pass

    # 6) Attach a QueueSink and start continuous acquisition:
    listener = MinimalListener()
    sink = ic4.QueueSink(listener)
    grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)
    sink.alloc_and_queue_buffers(5)

    # 7) Pop exactly one buffer (with timeout)
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
        arr = buf.numpy_wrap()
        np_img = np.array(arr, copy=False)

        # Convert to 8-bit for display if needed:
        if np_img.dtype == np.uint16:
            img8 = (np_img >> 8).astype(np.uint8)
        else:
            img8 = np_img

        # If multi‐channel, assume BGR8:
        if img8.ndim == 3 and img8.shape[2] == 3:
            display = img8
        else:
            # Single channel
            display = img8 if img8.ndim == 2 else img8[:, :, 0]

        cv2.imshow("One Frame", display)
        cv2.waitKey(0)
        cv2.destroyAllWindows()

        # Release buffer
        try:
            buf.release()
        except:
            pass

    # 8) Clean up
    try:
        grabber.acquisition_stop()
    except:
        pass
    grabber.device_close()


if __name__ == "__main__":
    main()
