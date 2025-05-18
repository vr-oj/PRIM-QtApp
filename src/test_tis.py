import imagingcontrol4 as ic4
import cv2


def main():
    # 1) Init
    ic4.Library.init()

    # 2) Enumerate & open
    cams = ic4.DeviceEnum.devices()
    if not cams:
        raise RuntimeError("No TIS cameras found! Is the driver installed?")
    info = cams[0]
    print(f"Opening camera: {info.model_name}, S/N {info.serial}")

    grabber = ic4.Grabber()
    grabber.device_open(info)

    # 3) Configure exposure
    grabber.device_property_map.set_value(ic4.PropId.EXPOSURE_TIME, 20000)

    # 4) Set up SnapSink & start acquisition
    sink = ic4.SnapSink()
    grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)

    # 5) Grab one frame
    img_buf = sink.snap_single(1000)
    frame = img_buf.numpy_copy()

    # 6) Show it
    cv2.imshow("TIS Frame", frame)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

    # 7) Clean up properly
    grabber.stream_stop()  # stop streaming
    grabber.device_close()  # close the device :contentReference[oaicite:0]{index=0}
    ic4.Library.exit()  # shut down the library


if __name__ == "__main__":
    main()
