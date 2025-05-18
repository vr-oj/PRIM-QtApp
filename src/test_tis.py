import imagingcontrol4 as ic4
import cv2


def main():
    # 1) Init the library
    ic4.Library.init()

    # 2) Enumerate and pick the first TIS camera
    cams = ic4.DeviceEnum.devices()
    if not cams:
        raise RuntimeError("No TIS cameras found! Is the driver installed?")
    info = cams[0]
    print(f"Opening camera: {info.model_name}, S/N {info.serial}")

    # 3) Open it
    grabber = ic4.Grabber()
    grabber.device_open(info)  # or: grabber = ic4.Grabber(info)

    # 4) (Optional) configure a property, e.g. exposure
    #    You can browse all PropId enum members to find what you need.
    grabber.device_property_map.set_value(ic4.PropId.EXPOSURE_TIME, 20000)

    # 5) Set up a SnapSink for on‐demand capture
    sink = ic4.SnapSink()
    grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)

    # 6) Snap one image (timeout in ms)
    img_buf = sink.snap_single(1000)

    # 7) Get a writable NumPy array
    frame = img_buf.numpy_copy()  # shape (H, W, C)

    # 8) Display with OpenCV
    cv2.imshow("TIS Frame", frame)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

    # 9) Clean up
    grabber.stream_stop()
    grabber.close()
    ic4.Library.exit()


if __name__ == "__main__":
    main()
