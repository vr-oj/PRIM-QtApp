import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage


class SDKCameraThread(QThread):
    """
    QThread that uses The Imaging Source IC Imaging Control 4 SDK
    to grab frames from a DMK 33UX250 and emit them as QImage objects.
    """

    frame_ready = pyqtSignal(QImage)

    def __init__(self, exposure=20000, fps=20, parent=None):
        super().__init__(parent)
        self.exposure = exposure
        self.fps = fps
        # interval between frames in milliseconds
        self._interval = int(1000 / self.fps)
        self._running = False

    def run(self):
        # Initialize the IC4 library
        ic4.Library.init()

        # 1) Enumerate connected TIS cameras
        cams = ic4.DeviceEnum.devices()
        if not cams:
            print("No TIS cameras found!")
            ic4.Library.exit()
            return
        info = cams[0]
        print(f"Using camera: {info.model_name} (S/N {info.serial})")

        # 2) Open camera
        grabber = ic4.Grabber()
        grabber.device_open(info)

        # 3) Grab the property map once
        pm = grabber.device_property_map

        # 4) Enumerate supported widths before setting anything
        try:
            entries = pm.get_entries(ic4.PropId.WIDTH)
            print("Supported widths:", [e.value for e in entries])
        except ic4.IC4Exception as e:
            print("⚠️ Couldn’t enumerate widths:", e)

        # 5) Safely set width, height, format, and exposure
        for prop, val in (
            (ic4.PropId.WIDTH, 640),
            (ic4.PropId.HEIGHT, 480),
            (ic4.PropId.PIXEL_FORMAT, "Mono8"),
            (ic4.PropId.EXPOSURE_TIME, self.exposure),
        ):
            try:
                pm.set_value(prop, val)
            except ic4.IC4Exception as e:
                print(f"⚠️ Couldn’t set {prop.name} to {val!r}: {e}")

        # 6) Prepare the sink and start acquisition safely
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

        # 7) Capture loop
        self._running = True
        while self._running:
            try:
                img_buf = sink.snap_single(1000)
                frame = img_buf.numpy_copy()  # H×W×C numpy array

                # Convert to QImage for Qt display
                h, w = frame.shape[:2]
                bytes_per_line = frame.strides[0]
                image = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
                self.frame_ready.emit(image)
            except Exception as e:
                print("Error grabbing frame:", e)
                break

            # Throttle frame rate
            self.msleep(self._interval)

        # 8) Cleanup
        try:
            grabber.stream_stop()
        except Exception:
            pass
        grabber.device_close()
        del img_buf, sink, grabber, info, cams
        ic4.Library.exit()

    def stop(self):
        # Signal the loop to end and wait for thread exit
        self._running = False
        try:
            self.wait()
        except RuntimeError:
            pass
