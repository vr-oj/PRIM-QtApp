import logging
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal, QMutex
from PyQt5.QtGui import QImage
from imagingcontrol4.properties import PropInteger
from imagingcontrol4 import PropId

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    frame_ready = pyqtSignal(QImage, object)
    camera_error = pyqtSignal(str, str)
    camera_resolutions_available = pyqtSignal(list)
    camera_properties_available = pyqtSignal(dict)  # <-- new

    def __init__(
        self,
        exposure_us=20000,
        target_fps=20,
        width=640,
        height=480,
        pixel_format="Mono8",
        parent=None,
    ):
        super().__init__(parent)
        self._mutex = QMutex()
        self._stop_requested = False
        self.target_fps = target_fps

        # capture settings
        self.desired_width = width
        self.desired_height = height
        self.desired_pixel_format = pixel_format
        self.desired_exposure = exposure_us
        self.desired_gain = None

        # pending updates
        self._pending_exposure = None
        self._pending_gain = None

    def update_exposure(self, new_exp_us: int):
        self._pending_exposure = new_exp_us

    def update_gain(self, new_gain: int):
        self._pending_gain = new_gain

    def run(self):
        self._stop_requested = False
        log.info(
            f"Camera thread start (FPS={self.target_fps}, Exp={self.desired_exposure}µs)"
        )
        grabber = None

        try:
            # 1) discover & open
            devices = ic4.DeviceEnum.devices()
            if not devices:
                raise RuntimeError("No TIS cameras found")
            dev = devices[0]
            grabber = ic4.Grabber()
            grabber.device_open(dev)
            log.info("Camera opened.")
            pm = grabber.device_property_map

            # 2) enumerate & emit resolutions
            try:
                wprop = pm.find(PropId.WIDTH)
                hprop = pm.find(PropId.HEIGHT)
                if isinstance(wprop, PropInteger) and isinstance(hprop, PropInteger):
                    widths = range(wprop.minimum, wprop.maximum + 1, wprop.increment)
                    heights = range(hprop.minimum, hprop.maximum + 1, hprop.increment)
                    modes = [f"{w}x{h}" for w in widths for h in heights]
                    self.camera_resolutions_available.emit(modes)
            except Exception as e:
                log.warning(f"Couldn’t enumerate resolutions: {e}")

            # 3) now gather *all* control props
            props = {}
            for name, pid in (
                ("exposure", PropId.EXPOSURE_TIME),
                ("gain", PropId.GAIN),
                ("brightness", PropId.BRIGHTNESS),
            ):
                try:
                    p = pm.find(pid)
                    if isinstance(p, PropInteger):
                        val = pm.get_value(pid)
                        entry = {
                            "enabled": True,
                            "min": p.minimum,
                            "max": p.maximum,
                            "value": val,
                        }
                    else:
                        entry = {"enabled": False, "min": 0, "max": 0, "value": 0}
                except Exception:
                    entry = {"enabled": False, "min": 0, "max": 0, "value": 0}

                # auto‐exposure only for exposure
                if name == "exposure":
                    try:
                        ae = pm.get_value_str(PropId.AUTO_EXPOSURE)
                        entry["is_auto_on"] = ae.lower() in ("on", "true", "1")
                    except Exception:
                        entry["is_auto_on"] = False

                props[name] = entry

            # ROI
            try:
                rx = pm.get_value(PropId.REGION_X)
                ry = pm.get_value(PropId.REGION_Y)
                rw = pm.get_value(PropId.REGION_WIDTH)
                rh = pm.get_value(PropId.REGION_HEIGHT)
                max_w = pm.find(PropId.REGION_WIDTH).maximum
                max_h = pm.find(PropId.REGION_HEIGHT).maximum
                roi = {
                    "x": rx,
                    "y": ry,
                    "w": rw,
                    "h": rh,
                    "max_w": max_w,
                    "max_h": max_h,
                }
            except Exception:
                roi = {"x": 0, "y": 0, "w": 0, "h": 0, "max_w": 0, "max_h": 0}

            all_props = {"controls": props, "roi": roi}
            self.camera_properties_available.emit(all_props)  # <-- emit

            # 4) configure free-run
            for pid, val in (
                (PropId.ACQUISITION_MODE, "Continuous"),
                (PropId.TRIGGER_MODE, "Off"),
            ):
                try:
                    pm.set_value(pid, val)
                except ic4.IC4Exception as e:
                    log.warning(f"Couldn’t set {pid.name}: {e}")

            # 5) set pixel format, size, exposure
            fmt = pm.get_value_str(PropId.PIXEL_FORMAT)
            if fmt != self.desired_pixel_format:
                pm.set_value(PropId.PIXEL_FORMAT, self.desired_pixel_format)
            for pid, v in (
                (PropId.WIDTH, self.desired_width),
                (PropId.HEIGHT, self.desired_height),
                (PropId.EXPOSURE_TIME, self.desired_exposure),
            ):
                pm.set_value(pid, v)

            # 6) start streaming…
            sink = ic4.SnapSink()
            grabber.stream_setup(
                sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            log.info("Acquisition started.")

            while True:
                self._mutex.lock()
                stop = self._stop_requested
                self._mutex.unlock()
                if stop:
                    break

                # apply pending exposure
                if self._pending_exposure is not None:
                    try:
                        pm.set_value(ic4.PropId.EXPOSURE_TIME, self._pending_exposure)
                        log.info(f"Exposure set to {self._pending_exposure}")
                        self.desired_exposure = self._pending_exposure
                    except ic4.IC4Exception as e:
                        log.warning(f"Failed to set exposure: {e}")
                    finally:
                        self._pending_exposure = None

                # apply pending gain
                if self._pending_gain is not None:
                    try:
                        pm.set_value(ic4.PropId.GAIN, self._pending_gain)
                        log.info(f"Gain set to {self._pending_gain}")
                        self.desired_gain = self._pending_gain
                    except ic4.IC4Exception as e:
                        log.warning(f"Failed to set gain: {e}")
                    finally:
                        self._pending_gain = None

                # apply pending brightness
                if self._pending_brightness is not None:
                    try:
                        pm.set_value(ic4.PropId.BRIGHTNESS, self._pending_brightness)
                        log.info(f"Brightness set to {self._pending_brightness}")
                    except ic4.IC4Exception as e:
                        log.warning(f"Failed to set brightness: {e}")
                    finally:
                        self._pending_brightness = None

                # apply pending auto-exposure
                if self._pending_auto_exposure is not None:
                    try:
                        val = "On" if self._pending_auto_exposure else "Off"
                        pm.set_value(ic4.PropId.AUTO_EXPOSURE, val)
                        log.info(
                            f"Auto Exposure {'enabled' if self._pending_auto_exposure else 'disabled'}"
                        )
                    except ic4.IC4Exception as e:
                        log.warning(f"Failed to toggle auto-exposure: {e}")
                    finally:
                        self._pending_auto_exposure = None

                try:
                    timeout = max(int(1000 / self.target_fps * 2), 100)
                    buf = sink.snap_single(timeout_ms=timeout)
                    frame = buf.numpy_copy()
                    h, w = frame.shape[:2]
                    fmt = pm.get_value_str(ic4.PropId.PIXEL_FORMAT)

                    if frame.ndim == 2 or (frame.ndim == 3 and frame.shape[2] == 1):
                        gray = frame if frame.ndim == 2 else frame[..., 0]
                        img = QImage(gray.data, w, h, w, QImage.Format_Grayscale8)
                    elif (
                        fmt in ("RGB8", "BGR8")
                        and frame.ndim == 3
                        and frame.shape[2] == 3
                    ):
                        bpl = w * 3
                        if fmt == "RGB8":
                            img = QImage(frame.data, w, h, bpl, QImage.Format_RGB888)
                        else:
                            conv = frame[..., ::-1].copy()
                            img = QImage(conv.data, w, h, bpl, QImage.Format_RGB888)
                    else:
                        continue

                    self.frame_ready.emit(img.copy(), frame.copy())
                    del buf

                except ic4.IC4Exception as snap_err:
                    if snap_err.code == ic4.ErrorCode.Timeout:
                        continue
                    self.camera_error.emit(
                        f"Snap Error: {snap_err}", str(snap_err.code)
                    )
                    break

        except Exception as e:
            log.error("Camera thread error", exc_info=True)
            self.camera_error.emit(str(e), "THREAD_ERROR")

        finally:
            if grabber:
                try:
                    if grabber.is_streaming:
                        grabber.stream_stop()
                    if grabber.is_device_open:
                        grabber.device_close()
                except Exception as cleanup:
                    log.warning(f"Cleanup failed: {cleanup}")
            log.info("Camera thread finished.")

    def stop(self):
        self._mutex.lock()
        self._stop_requested = True
        self._mutex.unlock()
