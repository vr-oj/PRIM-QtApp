import imagingcontrol4 as ic4
import numpy as np
import cv2  # or PyQt/QImage

# 1) Initialize and enumerate
ic4.Library.init()
devices = ic4.DeviceEnum.devices()
grab = ic4.Grabber()
grab.device_open(devices[0])

# 2) (Optional) configure exposure/gain/whatever
pm = grab.device_property_map
prop = pm.find_integer(ic4.PropId.EXPOSURE_TIME)
prop.value = 5000  # 5 ms exposure
pm.find_boolean(ic4.PropId.EXPOSURE_AUTO).value = False


# 3) Attach a QueueSink
class L(ic4.QueueSinkListener):
    def frames_queued(self, sink, *args):
        pass

    def sink_connected(self, sink, *args):
        pass


listener = L()
sink = ic4.QueueSink(listener)
grab.stream_setup(sink, ic4.StreamSetupOption.ACQUISITION_START)
sink.alloc_and_queue_buffers(5)

# 4) Pop one frame
buf = None
while buf is None:
    buf = sink.try_pop_output_buffer()
arr = buf.numpy_wrap()
img = np.array(arr, copy=False)  # raw pixels
buf.release()

# 5) Convert and show (OpenCV example)
if img.dtype == np.uint16:
    img8 = (img >> 8).astype(np.uint8)
else:
    img8 = img

if img8.ndim == 3 and img8.shape[2] == 3:
    cv2.imshow("One Frame", img8)
else:
    cv2.imshow("One Frame", img8[:, :, 0])  # grayscale
cv2.waitKey(0)
cv2.destroyAllWindows()

# 6) Cleanup
grab.acquisition_stop()
grab.device_close()
