from imagingcontrol4.properties import PropInteger
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage


class SDKCameraThread(QThread):
    frame_ready = pyqtSignal(QImage)

    def __init__(self, exposure=20000, fps=20, parent=None):
        super().__init__(parent)
        self.exposure = exposure
        self.fps = fps
        self._interval = int(1000 / self.fps)
        self._running = False

    def run(self):
        # 1) Initialize the IC4 library
        ic4.Library.init()

        # 2) Enumerate cameras
        cams = ic4.DeviceEnum.devices()
        if not cams:
            print("No TIS cameras found!")
            ic4.Library.exit()
            return
        info = cams[0]
        print(f"Using camera: {info.model_name} (S/N {info.serial})")

        # 3) Open device
        grabber = ic4.Grabber()
        grabber.device_open(info)

        # 4) Grab the property map once
        pm = grabber.device_property_map

        # 5) Properly enumerate 'WIDTH' integer property
        try:
            width_prop = pm.find(ic4.PropId.WIDTH)
            if isinstance(width_prop, PropInteger):
                wmin = width_prop.minimum
                wmax = width_prop.maximum
                winc = width_prop.increment
                supported = list(range(wmin, wmax + 1, winc))
                print(f"Supported widths: {supported}")
            else:
                print("⚠️ WIDTH property is not integer‐type:", type(width_prop))
        except ic4.IC4Exception as e:
            print("⚠️ Couldn’t access WIDTH property:", e)

        # 6) Safely set desired properties
        for prop, val in (
            (ic4.PropId.WIDTH, 640),  # replace 640 if not supported
            (ic4.PropId.HEIGHT, 480),
            (ic4.PropId.PIXEL_FORMAT, "Mono8"),
            (ic4.PropId.EXPOSURE_TIME, self.exposure),
        ):
            try:
                pm.set_value(prop, val)
            except ic4.IC4Exception as e:
                print(f"⚠️ Couldn’t set {prop.name} to {val!r}: {e}")

        # 7) Start acquisition
        sink = ic4.SnapSink()
        try:
            grabber.stream_setup(
                sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
        except ic4.IC4Exception as e:
            print("Failed to start acquisition:", e)
            grabber.device_close()
            ic4.Library.exit()
            return

        # 8) Capture loop
        self._running = True
        while self._running:
            try:
                img_buf = sink.snap_single(1000)
                frame = img_buf.numpy_copy()
                h, w = frame.shape[:2]
                bytes_per_line = frame.strides[0]
                image = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
                self.frame_ready.emit(image)
            except Exception as ex:
                print("Error grabbing frame:", ex)
                break
            self.msleep(self._interval)

        # 9) Cleanup
        try:
            grabber.stream_stop()
        except Exception:
            pass
        grabber.device_close()
        del img_buf, sink, grabber, info, cams
        ic4.Library.exit()

    def stop(self):
        self._running = False
        try:
            self.wait()
        except RuntimeError:
            pass
