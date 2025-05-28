# PRIM-QTAPP/prim_app/threads/sdk_camera_thread.py
import re
import numpy as np
import logging
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class MinimalSinkListener(ic4.QueueSinkListener):
    def __init__(self, owner_name="DefaultListener"):
        super().__init__()
        self.owner_name = owner_name
        log.debug(f"MinimalSinkListener '{self.owner_name}' created.")

    def frame_ready(self, sink: ic4.QueueSink, buffer: ic4.ImageBuffer, userdata: any):
        pass

    def frames_queued(self, sink: ic4.QueueSink):
        pass

    def sink_connected(
        self, sink: ic4.QueueSink, image_type_proposed: ic4.ImageType, userdata: any
    ) -> bool:
        log.debug(
            f"Listener '{self.owner_name}': Sink connected. Grabber proposed ImageType: {image_type_proposed}. Accepting."
        )
        return True

    def sink_disconnected(self, sink: ic4.QueueSink):
        log.debug(f"Listener '{self.owner_name}': Sink disconnected from {sink}.")
        pass

    def sink_property_changed(
        self, sink: ic4.QueueSink, property_name: str, userdata: any
    ):
        pass


class SDKCameraThread(QThread):
    frame_ready = pyqtSignal(QImage, object)
    camera_error = pyqtSignal(str, str)
    camera_info_updated = pyqtSignal(dict)
    exposure_params_updated = pyqtSignal(dict)

    def __init__(self, device_name=None, fps=10, parent=None):
        super().__init__(parent)
        self.device_identifier = device_name
        self.target_fps = float(fps)
        self._stop_requested = False
        self.grabber = None
        self.pm = None
        self.sink_listener = MinimalSinkListener(
            f"SDKThreadListener_{self.device_identifier or 'default'}"
        )
        log.info(
            f"SDKCameraThread initialized for '{self.device_identifier}', target_fps: {self.target_fps}"
        )

    def _attempt_set_property(
        self, prop_name: str, value_to_set: any, readable_value_for_log: str = None
    ):
        # ... (existing implementation) ...
        # unchanged from previous version
        prop_item = None
        success = False
        try:
            prop_item = self.pm.find(prop_name)
            if prop_item:
                log.info(f"Setting {prop_name} to {value_to_set}...")
                self.pm.set_value(prop_name, value_to_set)
                log.info(f"Property {prop_name} set.")
                success = True
            else:
                log.warning(f"Property {prop_name} not found.")
        except Exception as e:
            log.error(f"Error setting {prop_name}: {e}")
        return success

    def _query_and_emit_camera_parameters(self):
        """Queries key camera parameters and emits them via signals."""
        if not self.pm:
            log.warning("Cannot query camera parameters: PropertyMap not available.")
            return

        try:
            # --- General Camera Info ---
            info = {}
            props = [
                ("model", "DeviceModelName"),
                ("serial", "DeviceSerialNumber"),
                ("width", "Width"),
                ("height", "Height"),
                ("pixel_format", "PixelFormat"),
                ("fps", "AcquisitionFrameRate"),
            ]
            for key, name in props:
                p = self.pm.find(name)
                if p and p.is_readable:
                    info[key] = (
                        p.value_to_str()
                        if key in ("model", "serial", "pixel_format")
                        else p.value
                    )
                else:
                    info[key] = None
            self.camera_info_updated.emit(info)
            log.debug(f"camera_info_updated: {info}")

            # --- Exposure Parameters ---
            exp = {}
            p_auto = self.pm.find("ExposureAuto")
            if p_auto:
                exp["auto_options"] = [
                    e.name for e in getattr(p_auto, "available_entries", [])
                ]
                exp["auto_current"] = (
                    p_auto.value_to_str() if p_auto.is_readable else None
                )
                exp["auto_is_writable"] = p_auto.is_writable
            p_time = self.pm.find("ExposureTime")
            if p_time:
                exp["time_current_us"] = p_time.value if p_time.is_readable else None
                exp["time_min_us"] = getattr(p_time, "min", None)
                exp["time_max_us"] = getattr(p_time, "max", None)
                exp["time_is_writable"] = p_time.is_writable

            self.exposure_params_updated.emit(exp)
            log.debug(f"exposure_params_updated: {exp}")

        except Exception as e:
            log.error(f"Error querying camera parameters: {e}")

    @pyqtSlot(str)
    def set_exposure_auto(self, mode: str):
        """Sets ExposureAuto and re-queries parameters."""
        if self.pm and self.pm.find("ExposureAuto"):
            self._attempt_set_property("ExposureAuto", mode, mode)
            self._query_and_emit_camera_parameters()
        else:
            log.warning("ExposureAuto property unavailable.")

    @pyqtSlot(float)
    def set_exposure_time(self, us: float):
        """Sets ExposureTime (in microseconds) and re-queries parameters."""
        if self.pm and self.pm.find("ExposureTime"):
            self._attempt_set_property("ExposureTime", us, f"{us}us")
            self._query_and_emit_camera_parameters()
        else:
            log.warning("ExposureTime property unavailable.")

    def run(self):
        try:
            all_devices = ic4.DeviceEnum.devices()
            if not all_devices:
                raise RuntimeError("No IC4 devices found.")
            # Select device
            target_dev = None
            if self.device_identifier:
                for dev in all_devices:
                    if self.device_identifier in (
                        getattr(dev, "serial", ""),
                        getattr(dev, "unique_name", ""),
                        getattr(dev, "model_name", ""),
                    ):
                        target_dev = dev
                        break
                if not target_dev:
                    raise RuntimeError(f"Camera '{self.device_identifier}' not found.")
            else:
                target_dev = all_devices[0]

            # Open and configure
            self.grabber = ic4.Grabber()
            self.grabber.device_open(target_dev)
            self.pm = self.grabber.device_property_map
            # Default settings
            self._attempt_set_property("PixelFormat", ic4.PixelFormat.Mono8, "Mono8")
            self._attempt_set_property("Width", 640, "640")
            self._attempt_set_property("Height", 480, "480")
            self._attempt_set_property("AcquisitionMode", "Continuous", "Continuous")
            self._attempt_set_property("TriggerMode", "Off", "Off")
            # Disable auto exposure
            self._attempt_set_property("ExposureAuto", "Off", "Off")

            # Emit initial params
            self._query_and_emit_camera_parameters()

            # Start stream
            self.sink = ic4.QueueSink(listener=self.sink_listener)
            self.grabber.stream_setup(self.sink)
            if not self.grabber.is_acquisition_active:
                self.grabber.acquisition_start()

            # Acquisition loop
            while not self._stop_requested:
                # ... existing frame loop remains unchanged ...
                buf = self.sink.pop_output_buffer()
                if buf:
                    arr = buf.numpy_wrap()
                    fmt = QImage.Format_Grayscale8
                    if arr.ndim == 3 and arr.shape[2] == 3:
                        fmt = QImage.Format_BGR888
                    qimg = QImage(
                        arr.data, arr.shape[1], arr.shape[0], arr.strides[0], fmt
                    )
                    self.frame_ready.emit(qimg.copy(), arr.copy())
                    buf.release()
                else:
                    QThread.msleep(10)

        except Exception as e:
            log.error(f"SDKCameraThread error: {e}")
            self.camera_error.emit(str(e), type(e).__name__)
        finally:
            try:
                if self.grabber and self.grabber.is_acquisition_active:
                    self.grabber.acquisition_stop()
                if self.grabber and self.grabber.is_device_open:
                    self.grabber.device_close()
            except Exception as e:
                log.error(f"Error in cleanup: {e}")
            self.grabber = None
            self.pm = None
            log.info("SDKCameraThread cleanup complete.")

    def stop(self):
        log.info(f"Stopping SDKCameraThread for {self.device_identifier}.")
        self._stop_requested = True
        if self.isRunning():
            if not self.wait(3000):
                log.warning("Thread did not stop in time, terminating.")
                self.terminate()
                self.wait(500)
