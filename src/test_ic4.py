# test_ic4.py
import imagingcontrol4 as ic4

# 1) Initialize
ic4.Library.init()

# 2) Find cameras
devs = ic4.DeviceEnum.devices()
if not devs:
    raise RuntimeError("No cameras found")
cam = devs[0]
print("Found camera:", cam.model_name, cam.serial)

# 3) Open
grabber = ic4.Grabber()
grabber.device_open(cam)
print("Opened", cam.model_name)


# 4) Dummy listener for the sink callbacks
class DummyListener:
    def sink_connected(self, sink, image_type, min_buffers_required):
        return True

    def frames_queued(self, sink):
        pass

    def sink_disconnected(self, sink):
        pass


listener = DummyListener()

# 5) Create sink with listener and start streaming
sink = ic4.QueueSink(listener)
grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)
print("Stream started")

# 6) Grab one frame
buf = sink.pop_output_buffer()
print(
    f"Got buffer: {buf.image_type.width}×{buf.image_type.height} "
    f"{buf.image_type.pixel_format.name}"
)

# 7) Tear down
grabber.stream_stop()
grabber.device_close()
ic4.Library.exit()
