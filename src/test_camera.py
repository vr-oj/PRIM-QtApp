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
        # Must return True to allow streaming
        print(f"🔗 Sink connected: {image_type}, buffers={min_buffers_required}")
        return True

    def frames_queued(self, sink):
        pass

    def sink_disconnected(self, sink):
        print("🔌 Sink disconnected")


def main():
    # ── initialize the IC4 core library ──
    try:
        ic4.Library.init()
    except Exception as e:
        print("❌ Library.init() failed:", e)
        sys.exit(1)

    # ── enumerate cameras ──
    devs = ic4.DeviceEnum.devices()
    if not devs:
        print("❌ No cameras found by IC4.")
        sys.exit(1)
    cam = devs[0]
    print(f"Found camera: {cam.model_name!r}")

    # ── open the camera ──
    g = ic4.Grabber()
    try:
        g.device_open(cam)
        print("✅ Device opened.")
    except Exception as e:
        print("❌ Failed to open device:", e)
        sys.exit(1)

    # ── start streaming ──
    listener = DummySinkListener()
    sink = ic4.QueueSink(listener)
    if hasattr(sink, "accept_incomplete_frames"):
        sink.accept_incomplete_frames = False

    try:
        g.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)
        print("✅ Streaming started.")
    except Exception as e:
        print("❌ stream_setup failed:", e)
        g.device_close()
        sys.exit(1)

    # ── grab a few frames ──
    print("📸 Grabbing up to 10 frames…")
    got = 0
    t0 = time.monotonic()
    while got < 10 and (time.monotonic() - t0) < 5:
        try:
            buf = sink.pop_output_buffer()
        except ic4.IC4Exception as ex:
            name = ex.code.name if getattr(ex, "code", None) else ""
            if "NoData" in name or "Time" in name:
                time.sleep(0.05)
                continue
            print("❌ pop_output_buffer error:", name, ex)
            break

        if buf:
            w, h = buf.image_type.width, buf.image_type.height
            print(f"  • Frame {got+1}: {w}×{h}")
            got += 1
        else:
            time.sleep(0.05)

    if got == 0:
        print("⚠️  No frames received in 5 seconds.")
    else:
        print("✅ Done grabbing frames.")

    # ── clean up ──
    try:
        g.stream_stop()
    except:
        pass
    try:
        g.device_close()
    except:
        pass


if __name__ == "__main__":
    main()
