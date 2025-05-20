import imagingcontrol4 as ic4
import time, ctypes, logging

logging.basicConfig(level=logging.DEBUG)

grabber = ic4.Grabber()
dev = ic4.DeviceEnum.devices()[0]
grabber.device_open(dev)
pm = grabber.device_property_map
# configure pixel format + streaming here…
sink = ic4.QueueSink(None)
grabber.stream_setup(sink, ic4.StreamSetupOption.ACQUISITION_START)
for i in range(10):
    buf = sink.pop_output_buffer()
    print("Got buf:", buf)
    time.sleep(0.1)
grabber.stream_stop()
grabber.device_close()
