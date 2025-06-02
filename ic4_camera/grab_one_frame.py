# grab_one_frame.py

import time
import imagingcontrol4 as ic4
import numpy as np
import cv2


class _MinimalSinkListener(ic4.QueueSinkListener):
    def frames_queued(self, sink, *args):
        pass

    def sink_connected(self, sink, *args):
        pass


def main():
    try:
        ic4.Library.init()
    except ic4.IC4Exception as e:
        print("Library.init() failed:", e)
        return

    try:
        devices = ic4.DeviceEnum.devices()
    except ic4.IC4Exception as e:
        print("DeviceEnum.devices() failed:", e)
        return

    if not devices:
        print("No IC4 cameras found.")
        return

    # Pick device #0
    info = devices[0]
    print(f"Opening camera: {info.model_name}")

    try:
        grabber = ic4.Grabber()
        grabber.device_open(info)
    except ic4.IC4Exception as e:
        print("Failed to open camera:", e)
        return

    pm = grabber.device_property_map
    # (Optional) Force continuous mode & a moderate frame rate
    try:
        pm.set_value(ic4.PropId.ACQUISITION_MODE, "Continuous")
        pm.set_value(ic4.PropId.ACQUISITION_FRAME_RATE, 10.0)
    except:
        pass

    # Create sink & start acquisition
    listener = _MinimalSinkListener()
    sink = ic4.QueueSink(listener)
    grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)
    sink.alloc_and_queue_buffers(5)

    # Try to pop exactly one buffer (blocking until it arrives)
    buf = None
    timeout_s = 5.0
    t0 = time.time()
    while time.time() - t0 < timeout_s:
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
        # Convert to NumPy (this shares the buffer, no copy)
        arr = buf.numpy_wrap()
        np_img = np.array(arr, copy=False)  # shape = (H, W, C) dtype=uint8 or uint16

        # If it's 16-bit or single-channel, convert for display:
        if np_img.dtype == np.uint16:
            display8 = (np_img >> 8).astype(np.uint8)
            if display8.ndim == 2:
                cv2.imshow("Frame (downsampled 16→8)", display8)
            else:
                # assume shape (H, W, 3)
                bgr = cv2.cvtColor(display8, cv2.COLOR_BGR2RGB)
                cv2.imshow("Frame (downsampled 16→8)", bgr)
        elif np_img.dtype == np.uint8:
            if np_img.ndim == 2:
                cv2.imshow("Frame (gray8)", np_img)
            else:
                # IC4 often gives BGR8
                cv2.imshow("Frame (BGR8)", np_img)
        else:
            # fallback: show only the first channel
            gray = np_img[..., 0].astype(np.uint8)
            cv2.imshow("Frame (fallback gray)", gray)

        cv2.waitKey(0)
        cv2.destroyAllWindows()

        # Always release buffer so sink can reuse it
        try:
            buf.release()
        except:
            pass

    # Clean up
    try:
        grabber.acquisition_stop()
    except:
        pass
    grabber.device_close()


if __name__ == "__main__":
    main()
