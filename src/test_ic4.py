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

# 3) Helper to safely set properties
pm = grabber.device_property_map


def safe_set(name, val):
    p = pm.find(name)
    if p and p.is_available and not getattr(p, "is_readonly", False):
        pm.set_value(name, val)
        print(f"  Set {name} → {val}")


# 4) Configure exactly what we want:
safe_set("PixelFormat", "Mono8")
safe_set("Width", 2448)
safe_set("Height", 2048)
safe_set("AcquisitionFrameRate", 20.0)
safe_set("AcquisitionMode", "Continuous")
safe_set("TriggerMode", "Off")


# 5) Attach sink & start streaming
class DummyListener:
    def sink_connected(self, sink, image_type, min_buffers_required):
        return True

    def frames_queued(self, sink):
        pass

    def sink_disconnected(self, sink):
        pass


sink = ic4.QueueSink(DummyListener())
sink.timeout = 500  # ms
grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)
print("Stream started – waiting for first frame...")

# 6) Try to pop one buffer
buf = None
for _ in range(50):
    try:
        buf = sink.pop_output_buffer()
        break
    except ic4.IC4Exception:  # NoData
        time.sleep(0.1)

if buf is None:
    print("❌ No frames received – GenTL/driver issue remains")
else:
    w = buf.image_type.width
    h = buf.image_type.height
    pf = buf.image_type.pixel_format.name
    print(f"✅ got frame: {w}×{h}  {pf}")

# 7) Clean up
grabber.stream_stop()
grabber.device_close()
ic4.Library.exit()
