import logging
import time
import imagingcontrol4 as ic4

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

from imagingcontrol4.properties import (
    PropInteger,
    PropFloat,
    PropBoolean,
    PropEnumeration,
    PropEnumEntry,
)
from config import DEFAULT_FRAME_SIZE


log = logging.getLogger(__name__)

PROP_WIDTH = "Width"
PROP_HEIGHT = "Height"
PROP_PIXEL_FORMAT = "PixelFormat"
PROP_EXPOSURE_TIME = "ExposureTime"
PROP_EXPOSURE_AUTO = "ExposureAuto"
PROP_GAIN = "Gain"
PROP_OFFSET_X = "OffsetX"
PROP_OFFSET_Y = "OffsetY"
PROP_ACQUISITION_FRAME_RATE = "AcquisitionFrameRate"
PROP_ACQUISITION_MODE = "AcquisitionMode"
PROP_TRIGGER_MODE = "TriggerMode"


class DummySinkListener:
    def sink_connected(self, sink, image_type, min_buffers_required):
        log.debug(
            f"DummyListener: Sink connected. ImageType: {image_type}, MinBuffers: {min_buffers_required}"
        )
        return True

    def frames_queued(self, sink, userdata):
        pass

    def sink_disconnected(self, sink):
        log.debug(f"DummyListener: Sink disconnected (event for sink: {type(sink)}).")
        pass


class SDKCameraThread(QThread):
    frame_ready = pyqtSignal(QImage, object)
    camera_resolutions_available = pyqtSignal(list)
    camera_properties_updated = pyqtSignal(dict)
    camera_error = pyqtSignal(str, str)

    def __init__(
        self,
        device_info: "ic4.DeviceInfo" = None,
        target_fps: float = 20.0,
        desired_width: int = None,
        desired_height: int = None,
        desired_pixel_format: str = "Mono 8",
        parent=None,
    ):
        super().__init__(parent)
        self._stop_requested = False
        self.device_info = device_info
        self.target_fps = target_fps
        self.desired_width = desired_width
        self.desired_height = desired_height
        self.desired_pixel_format_str = desired_pixel_format
        self._pending_exposure_us = None
        self._pending_gain_db = None
        self._pending_auto_exposure = None
        self._pending_roi = None
        self.grabber = None
        self.sink = None
        self.pm = None
        self.current_frame_width = 0
        self.current_frame_height = 0
        self.current_pixel_format_name = ""
        self.actual_qimage_format = QImage.Format_Invalid
        self.dummy_listener = DummySinkListener()

    def request_stop(self):
        self._stop_requested = True

    def update_exposure(self, exp_us: int):
        self._pending_exposure_us = float(exp_us)

    def update_gain(self, gain_db: float):
        self._pending_gain_db = gain_db

    def update_auto_exposure(self, auto: bool):
        self._pending_auto_exposure = auto

    def update_roi(self, x: int, y: int, w: int, h: int):
        self._pending_roi = (x, y, w, h)

    def _is_prop_writable(self, prop_object):
        if prop_object and prop_object.is_available:
            return not getattr(prop_object, "is_readonly", True)
        return False

    def _set_property_value(self, prop_name: str, value_to_set):
        try:
            prop = self.pm.find(prop_name)
            if self._is_prop_writable(prop):
                self.pm.set_value(prop_name, value_to_set)
                log.info(f"Set {getattr(prop, 'name', prop_name)} to {value_to_set}")
                return True
            elif prop and prop.is_available:
                log.warning(
                    f"Prop {getattr(prop, 'name', prop_name)} not writable (readonly={getattr(prop, 'is_readonly', 'N/A')})."
                )
        except Exception as e:
            log.warning(f"Error setting {prop_name}: {e}")
        return False

    def _apply_pending_properties(self):
        if not self.pm or not self.grabber or not self.grabber.is_device_open:
            return
        if self._pending_auto_exposure is not None:
            val_str = "Continuous" if self._pending_auto_exposure else "Off"
            prop_auto = self.pm.find(PROP_EXPOSURE_AUTO)
            if prop_auto and prop_auto.is_available:
                success = self._set_property_value(
                    PROP_EXPOSURE_AUTO,
                    (
                        val_str
                        if isinstance(prop_auto, PropEnumeration)
                        else self._pending_auto_exposure
                    ),
                )
                if success and not self._pending_auto_exposure:
                    self._emit_camera_properties()
            self._pending_auto_exposure = None
        if self._pending_exposure_us is not None:
            prop_auto = self.pm.find(PROP_EXPOSURE_AUTO)
            auto_on = (
                prop_auto.value != "Off"
                if prop_auto
                and prop_auto.is_available
                and isinstance(prop_auto.value, str)
                else (
                    prop_auto.value
                    if prop_auto
                    and prop_auto.is_available
                    and isinstance(prop_auto.value, bool)
                    else False
                )
            )
            if not auto_on:
                self._set_property_value(PROP_EXPOSURE_TIME, self._pending_exposure_us)
            self._pending_exposure_us = None
        if self._pending_gain_db is not None:
            self._set_property_value(PROP_GAIN, self._pending_gain_db)
            self._pending_gain_db = None
        if self._pending_roi is not None:
            x, y, w, h = self._pending_roi
            if x == 0 and y == 0 and w == 0 and h == 0:
                self._set_property_value(PROP_OFFSET_X, 0)
                self._set_property_value(PROP_OFFSET_Y, 0)
            else:
                self._set_property_value(PROP_OFFSET_X, x)
                self._set_property_value(PROP_OFFSET_Y, y)
            self._pending_roi = None

    def _emit_camera_properties(self):
        if not self.pm:
            self.camera_properties_updated.emit({})
            return
        props_dict = {"controls": {}, "roi": {}}
        prop_map = {
            "exposure": (PROP_EXPOSURE_TIME, PROP_EXPOSURE_AUTO),
            "gain": (PROP_GAIN, None),
        }
        for name, (val_pn, auto_pn) in prop_map.items():
            try:
                p_info = {"enabled": False, "value": 0, "min": 0, "max": 0}
                prop_v = self.pm.find(val_pn)
                if prop_v and prop_v.is_available:
                    p_info["enabled"] = self._is_prop_writable(prop_v)
                    if isinstance(prop_v, (PropInteger, PropFloat)):
                        p_info.update(
                            {
                                "min": prop_v.minimum,
                                "max": prop_v.maximum,
                                "value": prop_v.value,
                            }
                        )
                    elif isinstance(prop_v, PropEnumeration):
                        p_info.update(
                            {
                                "options": [e.name for e in prop_v.entries],
                                "value": prop_v.value,
                            }
                        )
                    if auto_pn:
                        prop_a = self.pm.find(auto_pn)
                        if prop_a and prop_a.is_available:
                            p_info["auto_available"] = True
                            auto_val = prop_a.value
                            p_info["is_auto_on"] = (
                                (auto_val != "Off")
                                if isinstance(auto_val, str)
                                else bool(auto_val)
                            )
                            if p_info["is_auto_on"] and name == "exposure":
                                p_info["enabled"] = False
                props_dict["controls"][name] = p_info
            except Exception as e:
                log.debug(f"Error getting prop {name}: {e}")
                props_dict["controls"][name] = {"enabled": False}
        try:
            for k, pn_str in [
                ("w", PROP_WIDTH),
                ("h", PROP_HEIGHT),
                ("x", PROP_OFFSET_X),
                ("y", PROP_OFFSET_Y),
            ]:
                p = self.pm.find(pn_str)
                roi_props_dict[k] = p.value
                if hasattr(p, "maximum"):
                    roi_props_dict[f"max_{k}"] = p.maximum
            props_dict["roi"] = roi_props_dict
        except Exception:
            props_dict["roi"] = {}
        self.camera_properties_updated.emit(props_dict)

    def _emit_available_resolutions(self):
        if not self.pm:
            self.camera_resolutions_available.emit([])
            return
        try:
            w, h, pf = (
                self.pm.find(PROP_WIDTH).value,
                self.pm.find(PROP_HEIGHT).value,
                self.pm.find(PROP_PIXEL_FORMAT).value,
            )
            self.camera_resolutions_available.emit([f"{w}x{h} ({pf})"])
        except Exception as e:
            log.warning(f"Error emitting resolutions: {e}")

    def run(self):
        log.info(
            f"SDKCameraThread starting for: {self.device_info.model_name or 'Unknown'}"
        )
        self.grabber = ic4.Grabber()
        try:
            if not self.device_info:
                devices = ic4.DeviceEnum.devices()
                if not devices:
                    raise RuntimeError("No TIS cameras found.")
                self.device_info = devices[0]
            self.grabber.device_open(self.device_info)
            self.pm = self.grabber.device_property_map
            log.info(f"Device opened: {self.device_info.model_name}")

            try:  # Initial Config
                pf_prop = self.pm.find(PROP_PIXEL_FORMAT)
                pf_val = pf_prop.value
                desired_pf = self.desired_pixel_format_str
                if desired_pf and pf_val.lower().replace(
                    " ", ""
                ) != desired_pf.lower().replace(" ", ""):
                    if isinstance(pf_prop, PropEnumeration):
                        opts = [e.name for e in pf_prop.entries]
                        if desired_pf in opts:
                            pass
                        elif "Mono8" in opts:
                            desired_pf = "Mono8"
                        elif "Mono 8" in opts:
                            desired_pf = "Mono 8"
                        else:
                            desired_pf = pf_val
                    if desired_pf != pf_val:
                        self._set_property_value(PROP_PIXEL_FORMAT, desired_pf)
                self.current_pixel_format_name = self.pm.find(PROP_PIXEL_FORMAT).value
                if self.current_pixel_format_name.replace(" ", "") != "Mono8":
                    raise RuntimeError(f"Not Mono8: {self.current_pixel_format_name}")
                self.actual_qimage_format = QImage.Format_Grayscale8

                w_prop, h_prop = self.pm.find(PROP_WIDTH), self.pm.find(PROP_HEIGHT)
                if self.desired_width and self._is_prop_writable(w_prop):
                    self._set_property_value(PROP_WIDTH, self.desired_width)
                if self.desired_height and self._is_prop_writable(h_prop):
                    self._set_property_value(PROP_HEIGHT, self.desired_height)
                self.current_frame_width = (
                    w_prop.value
                    if w_prop and w_prop.is_available
                    else DEFAULT_FRAME_SIZE[0]
                )
                self.current_frame_height = (
                    h_prop.value
                    if h_prop and h_prop.is_available
                    else DEFAULT_FRAME_SIZE[1]
                )
                log.info(
                    f"Res: {self.current_frame_width}x{self.current_frame_height}, Format: {self.current_pixel_format_name}"
                )

                self._set_property_value(PROP_ACQUISITION_MODE, "Continuous")
                self._set_property_value(PROP_TRIGGER_MODE, "Off")
                self._set_property_value(
                    PROP_ACQUISITION_FRAME_RATE, float(self.target_fps)
                )
            except Exception as e:
                log.error(f"Config error: {e}", exc_info=True)
                self.camera_error.emit(f"Config: {e}", type(e).__name__)
                return

            self._apply_pending_properties()
            self._emit_available_resolutions()
            self._emit_camera_properties()
            self.sink = ic4.QueueSink(self.dummy_listener)
            if hasattr(self.sink, "accept_incomplete_frames"):
                self.sink.accept_incomplete_frames = False
            log.info("QueueSink created.")
            time.sleep(0.2)
            self.grabber.stream_setup(
                self.sink, ic4.StreamSetupOption.ACQUISITION_START
            )
            log.info("Stream setup with ACQUISITION_START attempted.")

            log.info("Entering frame acquisition loop...")
            fc, nbc, last_ft = 0, 0, time.monotonic()

            while not self._stop_requested:
                self._apply_pending_properties()
                buf = None
                try:
                    buf = self.sink.pop_output_buffer()  # Call with NO arguments
                except ic4.IC4Exception as e_pop:
                    # Check for NoData specifically
                    if hasattr(e_pop, "code") and e_pop.code == ic4.ErrorCode.NO_DATA:
                        nbc += 1
                        if (
                            nbc > 0 and nbc % 200 == 0
                        ):  # Log every ~10s if using 50ms sleep
                            log.warning(
                                f"Still no frames after {nbc * 0.05:.1f}s of polling (ErrorCode.NO_DATA from pop_output_buffer)."
                            )
                        self.msleep(50)  # Wait a bit before retrying
                        continue
                    # Check for actual TIMEOUT_ if that's a different expected non-data code
                    elif (
                        hasattr(e_pop, "code") and e_pop.code == ic4.ErrorCode.TIMEOUT_
                    ):  # Use TIMEOUT_
                        nbc += 1
                        if nbc > 0 and nbc % 200 == 0:
                            log.warning(
                                f"Still no frames after {nbc * 0.05:.1f}s of polling (ErrorCode.TIMEOUT_ from pop_output_buffer)."
                            )
                        self.msleep(50)
                        continue
                    # For other IC4Exceptions
                    log.error(
                        f"IC4Exception during pop_output_buffer: {e_pop}", exc_info=True
                    )
                    self.camera_error.emit(
                        str(e_pop),
                        f"SinkPop ({e_pop.code if hasattr(e_pop,'code') else 'N/A'})",
                    )
                    break
                # Removed the generic TypeError catch for pop_output_buffer() as the previous error confirmed its signature (takes no explicit args)

                if buf is None:  # Should primarily be caught by NO_DATA exception now
                    nbc += 1
                    if nbc > 0 and nbc % 200 == 0:
                        log.warning(
                            f"Still no frames after {nbc * 0.05:.1f}s of polling (buf is None from pop_output_buffer)."
                        )
                    self.msleep(50)
                    continue

                fc += 1
                log.info(
                    f"Frame {fc}: Buffer! W:{buf.image_type.width},H:{buf.image_type.height},Fmt:{buf.image_type.pixel_format.name}"
                )
                nbc = 0
                try:
                    img = QImage(
                        buf.mem_ptr,
                        buf.image_type.width,
                        buf.image_type.height,
                        buf.image_type.stride_bytes,
                        self.actual_qimage_format,
                    )
                    if not img.isNull():
                        self.frame_ready.emit(img.copy(), buf.mem_ptr)
                    else:
                        log.warning(f"Frame {fc}: QImage isNull.")
                finally:
                    pass

                now = time.monotonic()
                dt = now - last_ft
                target_int = 1.0 / self.target_fps if self.target_fps > 0 else 0.05
                if dt < target_int:
                    self.msleep(
                        max(0, int((target_int - dt) * 1000))
                    )  # Ensure non-negative sleep
                last_ft = time.monotonic()
            log.info("Exited frame acquisition loop.")
        except Exception as e:
            log.exception("Unhandled exception in SDKCameraThread.run()")
            self.camera_error.emit(str(e), type(e).__name__)
        finally:
            log.info("SDKCameraThread run() finishing...")
            if self.grabber:
                try:
                    if self.grabber.is_streaming:
                        self.grabber.stream_stop()
                        log.info("Stream stopped.")
                except:
                    pass
                try:
                    if self.grabber.is_device_open:
                        self.grabber.device_close()
                        log.info("Device closed.")
                except:
                    pass
            self.grabber, self.sink, self.pm = None, None, None
            log.info(
                f"SDKCameraThread ({self.device_info.model_name if self.device_info else 'N/A'}) fully stopped."
            )
