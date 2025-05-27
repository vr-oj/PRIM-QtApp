# PRIM-QTAPP/prim_app/threads/sdk_camera_thread.py
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
            try:
                prop_id = getattr(ic4.PropId, name)
                pm.set_value(prop_id, val)
                # Retrieve actual applied value
                actual = pm.get_value(prop_id)
                applied[name] = actual
            except Exception as e:
                code = getattr(e, "code", "")
                self.camera_error.emit(f"Failed to set {name} to {val}: {e}", str(code))
        if applied:
            self.properties_updated.emit(applied)

    def run(self):
        try:
            # Discover and open device
            devices = ic4.DeviceEnum.devices()
            if not devices:
                raise RuntimeError("No camera devices found")
            # Select by serial substring or default to first
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

            # Emit supported resolutions & formats if available
            try:
                modes = getattr(grabber.device_info, "video_modes", [])
                res_list = [f"{m.width}x{m.height}" for m in modes]
                fmt_list = sorted({m.pixel_format for m in modes})
            except Exception:
                # Fallback: query enumerations
                res_list = []
                fmt_list = []
            self.resolutions_updated.emit(res_list)
            self.pixel_formats_updated.emit(fmt_list)

            # FPS range
            try:
                fp_min = pm.get_min(ic4.PropId.AcquisitionFrameRate)
                fp_max = pm.get_max(ic4.PropId.AcquisitionFrameRate)
                self.fps_range_updated.emit(fp_min, fp_max)
                pm.set_value(ic4.PropId.AcquisitionFrameRate, self.fps)
            except Exception:
                log.debug("FPS range not available")

            # Exposure range & auto-exposure
            try:
                e_min = pm.get_min(ic4.PropId.ExposureTime)
                e_max = pm.get_max(ic4.PropId.ExposureTime)
                self.exposure_range_updated.emit(e_min, e_max)
                auto = pm.get_value(ic4.PropId.ExposureAuto) != 0
                self.auto_exposure_updated.emit(auto)
            except Exception:
                log.debug("Exposure range not available")

            # Gain range
            try:
                g_min = pm.get_min(ic4.PropId.Gain)
                g_max = pm.get_max(ic4.PropId.Gain)
                self.gain_range_updated.emit(g_min, g_max)
            except Exception:
                log.debug("Gain range not available")

            # Initial properties
            init_props = {}
            for pid in (
                ic4.PropId.ExposureTime,
                ic4.PropId.Gain,
                ic4.PropId.PixelFormat,
                ic4.PropId.AcquisitionFrameRate,
            ):
                try:
                    init_props[pid.name] = pm.get_value(pid)
                except Exception:
                    continue
            if init_props:
                self.properties_updated.emit(init_props)

            # Start streaming
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
                # Convert to QImage
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

            # Clean up
            try:
                grabber.acquisition_stop()
                grabber.stream_stop()
                grabber.device_close()
            except Exception:
                pass

        except Exception as ex:
            msg = getattr(ex, "message", str(ex))
            code = getattr(ex, "code", "")
            self.camera_error.emit(msg, str(code))

    def stop(self):
        """Signal the thread to stop and wait for exit."""
        self._stop_requested = True
        self.wait()
