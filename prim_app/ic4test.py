import imagingcontrol4 as ic4
import time

# Initialize and open camera
ic4.Library.init()
dev = ic4.DeviceEnum.devices()[0]
grabber = ic4.Grabber()
grabber.device_open(dev)

# Set properties
propmap = grabber.device_property_map
propmap.find_enumeration("AcquisitionMode").value = "Continuous"
propmap.find_enumeration("TriggerMode").value = "Off"
propmap.find_enumeration("ExposureAuto").value = "Off"
propmap.find_float("ExposureTime").value = 5000.0  # 5 ms
try:
    fr_node = propmap.find_float("AcquisitionFrameRate")
    fr_node.value = 10.0
except Exception as e:
    print(f"[FPS] Warning: {e}")


# Set up QueueSink with self as listener
class DummyListener:
    def frames_queued(self, sink):
        pass

    def sink_connected(self, sink, pixel_format, min_buffers_required):
        return True

    def sink_disconnected(self, sink):
        pass


listener = DummyListener()
sink = ic4.QueueSink(listener, [ic4.PixelFormat.Mono8], max_output_buffers=8)
grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)


# Measure frame rate
frame_count = 50
start_time = time.time()

for _ in range(frame_count):
    buf = sink.pop_output_buffer(1000)  # ← NO keyword argument!
    # optionally: arr = buf.numpy_wrap()
    buf.queue_buffer()

end_time = time.time()
elapsed = end_time - start_time
fps = frame_count / elapsed
print(f"[Measured FPS] {fps:.2f} over {frame_count} frames in {elapsed:.2f} seconds")

# Cleanup
grabber.stream_stop()
grabber.device_close()
ic4.Library.exit()
