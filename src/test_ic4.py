# test_ic4.py
import time
import imagingcontrol4 as ic4

# 1) Init the library
ic4.Library.init()

# 2) Enumerate & open
devs = ic4.DeviceEnum.devices()
if not devs:
    raise RuntimeError("No cameras found")
cam = devs[0]
print("Found camera:", cam.model_name, cam.serial)

grabber = ic4.Grabber()
grabber.device_open(cam)
print("Opened", cam.model_name)

# 3) Configure exactly as IC Capture does:
pm = grabber.device_property_map


def safe_set(name, val):
    p = pm.find(name)
    if p and p.is_available and not getattr(p, "is_readonly", False):
        p.set_value(val)
        print(f"  Set {name} → {val}")


safe_set("PixelFormat", "Mono8")
safe_set("AcquisitionMode", "Continuous")
safe_set("TriggerMode", "Off")
# you can optionally set AcquisitionFrameRate here if you like:
# safe_set("AcquisitionFrameRate", 10.0)


# 4) Attach a sink/listener and start streaming
class DummyListener:
    def sink_connected(self, sink, image_type, min_buffers_required):
        return True

    def frames_queued(self, sink):
        pass

    def sink_disconnected(self, sink):
        pass


sink = ic4.QueueSink(DummyListener())
sink.timeout = 500  # milliseconds
grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)
print("Stream started – waiting for first frame...")

# 5) Wait up to 5 seconds for a frame
buf = None
for _ in range(50):
    try:
        buf = sink.pop_output_buffer()
        break
    except ic4.IC4Exception:  # NoData yet
        time.sleep(0.1)

if not buf or not buf.is_valid:
    print("❌ still no frames – something’s wrong at the driver/GenTL level")
else:
    print(
        f"✅ got frame: {buf.image_type.width}×{buf.image_type.height} "
        f"{buf.image_type.pixel_format.name}"
    )

# 6) Clean up
grabber.stream_stop()
grabber.device_close()
ic4.Library.exit()
