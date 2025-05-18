import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage


class SDKCameraThread(QThread):
    """
    QThread that uses The Imaging Source IC Imaging Control 4 SDK
    to grab frames from a DMK 33UX250 and emit them as QImage objects.
    """

    frame_ready = pyqtSignal(QImage)

    def __init__(self, exposure=20000, parent=None):
        super().__init__(parent)
        self.exposure = exposure
        self._running = False

    def run(self):
        # Initialize the IC4 library
        ic4.Library.init()

        # Enumerate connected TIS cameras
        cams = ic4.DeviceEnum.devices()
        if not cams:
            print("No TIS cameras found!")
            ic4.Library.exit()
            return
        info = cams[0]
        print(f"Using camera: {info.model_name} (S/N {info.serial})")

        # Open camera
        grabber = ic4.Grabber()
        grabber.device_open(info)
        grabber.device_property_map.set_value(ic4.PropId.EXPOSURE_TIME, self.exposure)

        # Set up a SnapSink for on-demand grabbing
        sink = ic4.SnapSink()
        grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)

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

        # Cleanup
        grabber.stream_stop()
        grabber.device_close()
        del img_buf, sink, grabber, info, cams
        ic4.Library.exit()

    def stop(self):
        # Signal the loop to end and wait for thread exit
        self._running = False
        self.wait()
