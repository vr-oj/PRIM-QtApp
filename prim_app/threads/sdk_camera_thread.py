# PRIM_QTAPP/prim_app/threads/sdk_camera_thread.py
import numpy as np
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage


class SDKCameraThread(QThread):
    """
    Thread to grab live frames from a DMK camera using IC Imaging Control 4.
    Expects the GenTL producer to be loaded and ic4.Library initialized externally.
    Emits high-quality QImage frames and raw numpy arrays.
    """

    frame_ready = pyqtSignal(QImage, object)
    resolutions_updated = pyqtSignal(list)
    properties_updated = pyqtSignal(dict)
    camera_error = pyqtSignal(str, str)

    def __init__(self, device_name=None, fps=10, parent=None):
        super().__init__(parent)
        self.device_name = device_name
        self.fps = fps
        self._stop_requested = False
        self.grabber = None

    def apply_node_settings(self, settings: dict):
        """
        Apply a dict of GenICam feature settings (e.g., ExposureTime, Gain).
        Emits properties_updated with the actual applied values.
        """
        if not self.grabber:
            return
        prop_map = self.grabber.device_property_map
        applied = {}
        for name, val in settings.items():
            try:
                prop_id = getattr(ic4.PropId, name)
                prop_map.set_value(prop_id, val)
                applied[name] = prop_map.get_value(prop_id)
            except ic4.IC4Exception as e:
                self.camera_error.emit(
                    f"Failed to set {name} → {val}: {e}", e.code.name
                )
        if applied:
            self.properties_updated.emit(applied)

    def run(self):
        try:
            # Enumerate and open device
            devices = (
                ic4.DeviceEnum.devices()
            )  # ([theimagingsource.com](https://www.theimagingsource.com/en-us/documentation/ic4python/api-reference.html))
            if not devices:
                raise RuntimeError("No camera devices found")
            dev_info = next(
                (d for d in devices if self.device_name in d.unique_name), devices[0]
            )
            grabber = ic4.Grabber(
                dev_info
            )  # ([theimagingsource.com](https://www.theimagingsource.com/en-us/documentation/ic4python/api-reference.html))
            self.grabber = grabber

            # Enumerate available video modes
            modes = (
                grabber.device_info.video_modes
            )  # ([theimagingsource.com](https://www.theimagingsource.com/en-us/documentation/ic4python/api-reference.html))
            res_list = [f"{m.width}x{m.height} ({m.pixel_format})" for m in modes]
            self.resolutions_updated.emit(res_list)

            # Configure frame rate if supported
            try:
                grabber.device_property_map.set_value(
                    ic4.PropId.AcquisitionFrameRate, self.fps
                )
            except ic4.IC4Exception:
                pass

            # Emit initial property values
            props = {}
            for p in (ic4.PropId.ExposureTime, ic4.PropId.Gain, ic4.PropId.PixelFormat):
                try:
                    props[p.name] = grabber.device_property_map.get_value(p)
                except ic4.IC4Exception:
                    pass
            if props:
                self.properties_updated.emit(props)

            # Setup and start streaming
            sink = (
                ic4.QueueSink()
            )  # ([theimagingsource.com](https://www.theimagingsource.com/en-us/documentation/ic4python/api-reference.html))
            grabber.stream_setup(
                sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )  # ([theimagingsource.com](https://www.theimagingsource.com/en-us/documentation/ic4python/api-reference.html))

            # Acquire frames
            while not self._stop_requested and grabber.is_acquisition_active:
                try:
                    buf = sink.pop_output_buffer(1000)
                except ic4.IC4Exception:
                    continue
                if buf:
                    arr = buf.numpy_wrap()
                    if arr.ndim == 3 and arr.shape[2] == 3:
                        rgb = arr[..., ::-1]
                        qfmt = QImage.Format_RGB888
                        data = rgb
                    else:
                        mono = arr[..., 0] if arr.ndim == 3 else arr
                        qfmt = QImage.Format_Indexed8
                        data = mono
                    qimg = QImage(
                        data.data, data.shape[1], data.shape[0], data.strides[0], qfmt
                    )
                    self.frame_ready.emit(qimg.copy(), arr)
                    buf.release()

            # Cleanup
            grabber.acquisition_stop()
            grabber.stream_stop()
            grabber.device_close()

        except ic4.IC4Exception as ex:
            self.camera_error.emit(ex.message, ex.code.name)
        except Exception as ex:
            self.camera_error.emit(str(ex), "")

    def stop(self):
        self._stop_requested = True
        self.wait()
