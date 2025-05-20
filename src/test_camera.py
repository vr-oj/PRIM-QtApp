import os
import time
import sys
import imagingcontrol4 as ic4

# If you need to point at a specific .cti, uncomment and adjust:
os.environ["IC4_DLL_PATH"] = (
    r"C:\Program Files\The Imaging Source Europe GmbH\IC4 GenTL Driver for USB3Vision Devices 1.4\bin\ic4-gentl-u3v_x64.cti"
)


class DummySinkListener:
    def sink_connected(self, sink, image_type, min_buffers_required):
        print(f"🔗 Sink connected: {image_type}, buffers={min_buffers_required}")
        return True

    def frames_queued(self, sink):
        pass

    def sink_disconnected(self, sink):
        print("🔌 Sink disconnected")


def main():
    # ── 1) Init the IC4 library
    try:
        ic4.Library.init()
    except Exception as e:
        print("❌ Library.init() failed:", e)
        sys.exit(1)

    # ── 2) Enumerate & open
    devs = ic4.DeviceEnum.devices()
    if not devs:
        print("❌ No cameras found.")
        sys.exit(1)
    cam = devs[0]
    print(f"📷 Found camera: {cam.model_name!r}")

    grabber = ic4.Grabber()
    try:
        grabber.device_open(cam)
        print("✅ Device opened.")
    except Exception as e:
        print("❌ Failed to open device:", e)
        sys.exit(1)

    pm = grabber.device_property_map

    # ── 3) Dump a few key properties
    def dump_prop(name):
        try:
            p = pm.find(name)
            print(
                f" • {name}: value={p.value}, available={p.is_available}, readonly={getattr(p,'is_readonly',False)}"
            )
        except:
            print(f" • {name}: <error reading>")

    print("🔍 Current settings:")
    for n in (
        "PixelFormat",
        "Width",
        "Height",
        "AcquisitionMode",
        "TriggerMode",
        "ExposureAuto",
        "ExposureTime",
    ):
        dump_prop(n)

    # ── 4) Force continuous streaming & manual exposure
    try:
        pm.set_value("PixelFormat", pm.find("PixelFormat").entries[0].name)
        pm.set_value("Width", pm.find("Width").maximum)
        pm.set_value("Height", pm.find("Height").maximum)
        pm.set_value("AcquisitionMode", "Continuous")
        pm.set_value("TriggerMode", "Off")
        pm.set_value("AcquisitionFrameRate", 20.0)
        pm.set_value("ExposureAuto", "Off")  # turn off auto exposure
        pm.set_value("ExposureTime", 20000.0)  # 20 ms
        print("✅ Forced continuous-free-run + manual exposure")
    except Exception as e:
        print("❌ Failed to configure camera:", e)

    # ── 5) Start streaming
    listener = DummySinkListener()
    sink = ic4.QueueSink(listener)
    # allow incomplete for diagnostics:
    if hasattr(sink, "accept_incomplete_frames"):
        sink.accept_incomplete_frames = True

    try:
        grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)
        print("✅ Streaming started.")
    except Exception as e:
        print("❌ stream_setup failed:", e)
        grabber.device_close()
        sys.exit(1)

    # ── 6) Grab up to 10 frames
    print("📸 Grabbing up to 10 frames…")
    got = 0
    t0 = time.monotonic()
    while got < 10 and (time.monotonic() - t0) < 5:
        try:
            buf = sink.pop_output_buffer()
        except ic4.IC4Exception as ex:
            name = getattr(ex.code, "name", "")
            if "NoData" in name or "Time" in name:
                time.sleep(0.05)
                continue
            print("❌ pop_output_buffer error:", name, ex)
            break

        if buf:
            print(f"  • Frame {got+1}: {buf.image_type.width}×{buf.image_type.height}")
            got += 1
        else:
            time.sleep(0.05)

    if got == 0:
        print("⚠️  No frames received in 5 s. Check exposure/time or camera link.")
    else:
        print("✅ Done grabbing frames.")

    # ── 7) Tear down
    try:
        grabber.stream_stop()
    except:
        pass
    try:
        grabber.device_close()
    except:
        pass


if __name__ == "__main__":
    main()
