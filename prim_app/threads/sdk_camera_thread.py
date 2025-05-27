# PRIM-QTAPP/prim_app/threads/sdk_camera_thread.py
import re
import numpy as np
import logging
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    """
    Thread to grab live frames from a DMK camera using IC Imaging Control 4.
    Expects the GenTL producer to be loaded and ic4.Library initialized externally.
    Emits QImage frames, raw numpy arrays, and camera property updates via signals.
    """

    frame_ready = pyqtSignal(QImage, object)
    resolutions_updated = pyqtSignal(list)
    pixel_formats_updated = pyqtSignal(list)
    fps_range_updated = pyqtSignal(float, float)
    exposure_range_updated = pyqtSignal(float, float)
    gain_range_updated = pyqtSignal(float, float)
    auto_exposure_updated = pyqtSignal(bool)
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
        Apply GenICam feature settings (e.g., ExposureTime, Gain) to the opened device.
        Emits properties_updated with actual applied values.
        """
        if not self.grabber:
            return
        pm = self.grabber.device_property_map
        applied = {}
        for name, val in settings.items():
            # map CamelCase or snake_case to UPPER_SNAKE_CASE PropId name
            prop_name = (
                name
                if name.isupper()
                else re.sub(r"(?<!^)(?=[A-Z])", "_", name).upper()
            )
            try:
                prop_id = getattr(ic4.PropId, prop_name)
                pm.set_value(prop_id, val)
                # you may need to pick get_value_int/float/str/… here:
                actual = pm.get_value(prop_id)
                applied[prop_name] = actual
            except Exception as e:
                code = getattr(e, "code", "")
                self.camera_error.emit(
                    f"Failed to set {prop_name} to {val}: {e}", str(code)
                )

        if applied:
            self.properties_updated.emit(applied)

    def run(self):
        import re  # needed for the above mapping

        try:
            # Discover and open device
            devices = ic4.DeviceEnum.devices()
            if not devices:
                raise RuntimeError("No camera devices found")
            dev = next(
                (
                    d
                    for d in devices
                    if self.device_name
                    and self.device_name in getattr(d, "serial_number", "")
                ),
                devices[0],
            )

            grabber = ic4.Grabber()
            grabber.device_open(dev)
            self.grabber = grabber
            pm = grabber.device_property_map

            # Resolutions & pixel formats
            try:
                modes = getattr(grabber.device_info, "video_modes", [])
                res_list = [f"{m.width}x{m.height}" for m in modes]
                fmt_list = sorted({m.pixel_format for m in modes})
            except Exception:
                res_list, fmt_list = [], []
            self.resolutions_updated.emit(res_list)
            self.pixel_formats_updated.emit(fmt_list)

            # FPS
            try:
                lo = pm.get_min(ic4.PropId.AcquisitionFrameRate)
                hi = pm.get_max(ic4.PropId.AcquisitionFrameRate)
                self.fps_range_updated.emit(lo, hi)
                pm.set_value(ic4.PropId.AcquisitionFrameRate, self.fps)
            except Exception:
                log.debug("FPS range not available")

            # Exposure
            try:
                lo = pm.get_min(ic4.PropId.ExposureTime)
                hi = pm.get_max(ic4.PropId.ExposureTime)
                self.exposure_range_updated.emit(lo, hi)
                auto = pm.get_value(ic4.PropId.ExposureAuto) != 0
                self.auto_exposure_updated.emit(auto)
            except Exception:
                log.debug("Exposure range not available")

            # Gain
            try:
                lo = pm.get_min(ic4.PropId.Gain)
                hi = pm.get_max(ic4.PropId.Gain)
                self.gain_range_updated.emit(lo, hi)
            except Exception:
                log.debug("Gain range not available")

            # Initial props
            init = {}
            for pid in (
                ic4.PropId.ExposureTime,
                ic4.PropId.Gain,
                ic4.PropId.PixelFormat,
                ic4.PropId.AcquisitionFrameRate,
            ):
                try:
                    init[pid.name] = pm.get_value(pid)
                except Exception:
                    pass
            if init:
                self.properties_updated.emit(init)

            # Start acquisition
            sink = ic4.QueueSink()
            grabber.stream_setup(
                sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            grabber.acquisition_start()

            while not self._stop_requested and getattr(
                grabber, "is_acquisition_active", False
            ):
                try:
                    buf = sink.pop_output_buffer(1000)
                except Exception:
                    continue
                if not buf:
                    continue
                arr = buf.numpy_wrap()
                # convert to QImage
                if arr.ndim == 3 and arr.shape[2] == 3:
                    rgb = arr[..., ::-1]
                    img = QImage(
                        rgb.data,
                        rgb.shape[1],
                        rgb.shape[0],
                        rgb.strides[0],
                        QImage.Format_RGB888,
                    )
                else:
                    mono = arr[..., 0] if arr.ndim == 3 else arr
                    img = QImage(
                        mono.data,
                        mono.shape[1],
                        mono.shape[0],
                        mono.strides[0],
                        QImage.Format_Indexed8,
                    )
                self.frame_ready.emit(img.copy(), arr)
                buf.release()

            # cleanup
            try:
                grabber.acquisition_stop()
                grabber.stream_stop()
                grabber.device_close()
            except Exception:
                pass

        except Exception as ex:
            msg = str(ex)
            code = getattr(ex, "code", "")
            self.camera_error.emit(msg, str(code))

    def stop(self):
        """Signal the thread to stop and wait for exit."""
        self._stop_requested = True
        self.wait()
