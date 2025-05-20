#!/usr/bin/env python3
import os
import time
import sys
import imagingcontrol4 as ic4

# If you need to point at a specific .cti, uncomment and adjust:
os.environ["IC4_DLL_PATH"] = (
    r"C:\Program Files\The Imaging Source Europe GmbH\IC4 GenTL Driver for USB3Vision Devices 1.4\bin\ic4-gentl-u3v_x64.cti"
)


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
    sink = ic4.QueueSink(None)
    if hasattr(sink, "accept_incomplete_frames"):
        sink.accept_incomplete_frames = False

    try:
        g.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)
    except Exception as e:
        print("❌ stream_setup failed:", e)
        g.device_close()
        sys.exit(1)

    print("✅ Streaming started. Grabbing up to 10 frames…")

    # ── grab a few frames ──
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
            w = buf.image_type.width
            h = buf.image_type.height
            print(f"📸 Frame {got+1}: {w}×{h}")
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
