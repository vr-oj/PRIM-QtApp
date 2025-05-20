#!/usr/bin/env python3
import imagingcontrol4 as ic4
import time
import sys


def main():
    devs = ic4.DeviceEnum.devices()
    if not devs:
        print("❌ No cameras found by IC4.")
        sys.exit(1)
    cam = devs[0]
    print(f"Found camera: {cam.model_name!r}")

    g = ic4.Grabber()
    try:
        g.device_open(cam)
        print("✅ Device opened.")
    except Exception as e:
        print("❌ Failed to open device:", e)
        sys.exit(1)

    sink = ic4.QueueSink(None)
    # reject incomplete frames if supported
    if hasattr(sink, "accept_incomplete_frames"):
        sink.accept_incomplete_frames = False

    g.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)
    print("✅ Streaming started. Grabbing 10 frames…")

    got = 0
    t0 = time.monotonic()
    while got < 10 and (time.monotonic() - t0) < 5:
        try:
            buf = sink.pop_output_buffer()
        except ic4.IC4Exception as ex:
            name = ex.code.name if getattr(ex, "code", None) else ""
            if "NoData" in name or "Time" in name:
                # no frame yet—sleep and retry
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
            # sometimes it returns None
            time.sleep(0.05)

    if got == 0:
        print("⚠️  No frames received in 5 seconds.")
    else:
        print("✅ Done grabbing frames.")

    # clean up
    g.stream_stop()
    g.device_close()


if __name__ == "__main__":
    main()
