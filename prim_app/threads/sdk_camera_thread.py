# PRIM-QTAPP/prim_app/threads/sdk_camera_thread.py
import numpy as np
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage


class SDKCameraThread(QThread):
    """
    Thread to grab live frames from a DMK camera using IC Imaging Control 4.
    Expects the GenTL producer to be loaded and ic4.Library initialized externally.
    Emits high-quality QImage frames and raw numpy arrays and camera property updates.
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
        self.device_name = device_name  # serial or unique identifier
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
                applied[name] = pm.get_value(prop_id)
            except ic4.IC4Exception as e:
                self.camera_error.emit(f"Failed to set {name}→{val}: {e}", e.code.name)
        if applied:
            self.properties_updated.emit(applied)

    def run(self):
        try:
            # Initialize grabber and open device matching serial_pattern or first available
            devices = ic4.DeviceEnum.devices()
            if not devices:
                raise RuntimeError("No camera devices found")
            dev_info = next(
                (
                    d
                    for d in devices
                    if self.device_name
                    and self.device_name in getattr(d, "serial_number", "")
                ),
                devices[0],
            )
            grabber = ic4.Grabber(dev_info)
            self.grabber = grabber
            pm = grabber.device_property_map

            # 1) Video modes → resolutions + pixel formats
            modes = grabber.device_info.video_modes
            res_list = [f"{m.width}x{m.height}" for m in modes]
            fmt_list = [m.pixel_format for m in modes]
            self.resolutions_updated.emit(res_list)
            self.pixel_formats_updated.emit(sorted(set(fmt_list)))

            # 2) FPS range
            try:
                fp_min = pm.get_min(ic4.PropId.AcquisitionFrameRate)
                fp_max = pm.get_max(ic4.PropId.AcquisitionFrameRate)
                self.fps_range_updated.emit(fp_min, fp_max)
                pm.set_value(ic4.PropId.AcquisitionFrameRate, self.fps)
            except ic4.IC4Exception:
                pass

            # 3) Exposure range + auto exposure state
            try:
                exp_min = pm.get_min(ic4.PropId.ExposureTime)
                exp_max = pm.get_max(ic4.PropId.ExposureTime)
                self.exposure_range_updated.emit(exp_min, exp_max)
                auto = pm.get_value(ic4.PropId.ExposureAuto) != 0
                self.auto_exposure_updated.emit(auto)
            except ic4.IC4Exception:
                pass

            # 4) Gain range
            try:
                g_min = pm.get_min(ic4.PropId.Gain)
                g_max = pm.get_max(ic4.PropId.Gain)
                self.gain_range_updated.emit(g_min, g_max)
            except ic4.IC4Exception:
                pass

            # Emit initial applied property values
            initial_props = {}
            for pid in (
                ic4.PropId.ExposureTime,
                ic4.PropId.Gain,
                ic4.PropId.PixelFormat,
                ic4.PropId.AcquisitionFrameRate,
            ):
                try:
                    initial_props[pid.name] = pm.get_value(pid)
                except ic4.IC4Exception:
                    pass
            if initial_props:
                self.properties_updated.emit(initial_props)

            # Setup streaming sink
            sink = ic4.QueueSink()
            grabber.stream_setup(
                sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            grabber.acquisition_start()

            # Continuous frame acquisition
            while not self._stop_requested and grabber.is_acquisition_active:
                try:
                    buf = sink.pop_output_buffer(1000)
                except ic4.IC4Exception:
                    continue
                if buf:
                    arr = buf.numpy_wrap()
                    # Convert BGR or mono to QImage-friendly data
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
