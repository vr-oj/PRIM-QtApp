import imagingcontrol4 as ic4
import cv2


def main():
    ic4.Library.init()

    cams = ic4.DeviceEnum.devices()
    if not cams:
        raise RuntimeError("No TIS cameras found!")
    info = cams[0]
    print(f"Opening camera: {info.model_name}, S/N {info.serial}")

    grabber = ic4.Grabber()
    grabber.device_open(info)
    grabber.device_property_map.set_value(ic4.PropId.EXPOSURE_TIME, 20000)

    sink = ic4.SnapSink()
    grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)

    img_buf = sink.snap_single(1000)
    frame = img_buf.numpy_copy()

    cv2.imshow("TIS Frame", frame)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

    # ——— clean up in correct order ———
    grabber.stream_stop()
    grabber.device_close()

    del img_buf, sink, grabber, info, cams

    ic4.Library.exit()


if __name__ == "__main__":
    main()
