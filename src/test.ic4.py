import imagingcontrol4 as ic4

# Initialize library
ic4.Library.init()

# Find first camera
devs = ic4.DeviceEnum.devices()
if not devs:
    raise RuntimeError("No cameras found")
dev = devs[0]
print("Found camera:", dev.model_name, dev.serial)

# Open, configure minimal settings, grab one frame
grabber = ic4.Grabber()
grabber.device_open(dev)

# Force a known safe resolution
grabber.device_property_map.find("Width").value = 640
grabber.device_property_map.find("Height").value = 480
grabber.device_property_map.find("PixelFormat").value = "Mono8"

# Start streaming
sink = ic4.QueueSink()
grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)

# Pull one buffer
buf = sink.pop_output_buffer()
print("Grabbed frame:", buf.image_type.width, "x", buf.image_type.height)

# Clean up
grabber.stream_stop()
grabber.device_close()
