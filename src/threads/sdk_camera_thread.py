import logging
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal, QMutex
from PyQt5.QtGui import QImage
from imagingcontrol4.properties import PropInteger, PropBoolean

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    frame_ready = pyqtSignal(QImage, object)
    camera_error = pyqtSignal(str, str)
    camera_resolutions_available = pyqtSignal(list)
    # UI listens for this to populate sliders/checkboxes
    camera_properties_updated = pyqtSignal(dict)

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

        # Desired settings
        self.desired_width = width
        self.desired_height = height
        self.desired_pixel_format = pixel_format
        self.desired_exposure = exposure_us
        self.desired_gain = None
        self.desired_auto_exposure = None

        # Pending updates from the UI
        self._pending_exposure = None
        self._pending_gain = None
        self._pending_auto_exposure = None

    def update_exposure(self, new_exp_us: int):
        self._pending_exposure = new_exp_us

    def update_gain(self, new_gain: int):
        self._pending_gain = new_gain

    def update_auto_exposure(self, enable: bool):
        self._pending_auto_exposure = enable

    def run(self):
        self._stop_requested = False
        grabber = None
        try:
            # ─── Open camera ──────────────────────────────────────
            devices = ic4.DeviceEnum.devices()
            if not devices:
                raise RuntimeError("No TIS cameras found")
            dev = devices[0]
            log.info(f"Using camera {dev.model_name} (S/N {dev.serial})")

            grabber = ic4.Grabber()
            grabber.device_open(dev)
            pm = grabber.device_property_map

            # ─── Enumerate resolutions ───────────────────────────
            try:
                w = pm.find(ic4.PropId.WIDTH)
                h = pm.find(ic4.PropId.HEIGHT)
                if isinstance(w, PropInteger) and isinstance(h, PropInteger):
                    modes = [
                        f"{wi}x{hi}"
                        for wi in range(w.minimum, w.maximum + 1, w.increment)
                        for hi in range(h.minimum, h.maximum + 1, h.increment)
                    ]
                    self.camera_resolutions_available.emit(modes)
            except Exception as e:
                log.warning(f"Couldn’t enumerate resolutions: {e}")

            # ─── Gather initial control ranges/values ────────────
            controls = {}

            def try_prop(name, pid):
                try:
                    prop = pm.find(pid)
                    log.debug(f"Found prop {name}: {prop} ({type(prop)})")
                    if isinstance(prop, PropInteger):
                        controls[name] = {
                            "enabled": True,
                            "min": prop.minimum,
                            "max": prop.maximum,
                            "value": prop.get(),
                        }
                    elif name == "auto_exposure" and isinstance(prop, PropBoolean):
                        on = bool(prop.get())
                        controls[name] = {
                            "enabled": True,
                            "min": 0,
                            "max": 1,
                            "value": on,
                            "is_auto_on": on,
                        }
                except Exception:
                    log.debug(f"Property {name} (PID {pid}) not available or failed.")

            # Always try these
            try_prop("exposure", ic4.PropId.EXPOSURE_TIME)
            try_prop("gain", ic4.PropId.GAIN)
            # auto-exposure uses EXPOSURE_AUTO
            if hasattr(ic4.PropId, "EXPOSURE_AUTO"):
                try_prop("auto_exposure", ic4.PropId.EXPOSURE_AUTO)

            # ROI defaults (you could enumerate sensor size if needed)
            roi = {"max_w": 0, "max_h": 0, "x": 0, "y": 0, "w": 0, "h": 0}

            # Emit to wire up UI sliders/checkboxes
            self.camera_properties_updated.emit({"controls": controls, "roi": roi})

            # ─── Configure and start acquisition ──────────────────
            for pid, val in (
                (ic4.PropId.ACQUISITION_MODE, "Continuous"),
                (ic4.PropId.TRIGGER_MODE, "Off"),
            ):
                try:
                    pm.set_value(pid, val)
                except Exception:
                    pass

            if pm.get_value_str(ic4.PropId.PIXEL_FORMAT) != self.desired_pixel_format:
                pm.set_value(ic4.PropId.PIXEL_FORMAT, self.desired_pixel_format)
            pm.set_value(ic4.PropId.WIDTH, self.desired_width)
            pm.set_value(ic4.PropId.HEIGHT, self.desired_height)
            pm.set_value(ic4.PropId.EXPOSURE_TIME, self.desired_exposure)

            sink = ic4.SnapSink()
            grabber.stream_setup(
                sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )

            # ─── Capture loop ─────────────────────────────────────
            while True:
                self._mutex.lock()
                stop = self._stop_requested
                self._mutex.unlock()
                if stop:
                    break

                # Apply any pending parameter changes
                if self._pending_exposure is not None:
                    try:
                        pm.set_value(ic4.PropId.EXPOSURE_TIME, self._pending_exposure)
                        self.desired_exposure = self._pending_exposure
                    except Exception:
                        pass
                    self._pending_exposure = None

                if self._pending_gain is not None:
                    try:
                        pm.set_value(ic4.PropId.GAIN, self._pending_gain)
                        self.desired_gain = self._pending_gain
                    except Exception:
                        pass
                    self._pending_gain = None

                if self._pending_auto_exposure is not None and hasattr(
                    ic4.PropId, "EXPOSURE_AUTO"
                ):
                    try:
                        pm.set_value(
                            ic4.PropId.EXPOSURE_AUTO, int(self._pending_auto_exposure)
                        )
                        self.desired_auto_exposure = self._pending_auto_exposure
                    except Exception:
                        pass
                    self._pending_auto_exposure = None

                # Snap a frame
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
            log.exception("Camera thread error")
            self.camera_error.emit(str(e), "THREAD_ERROR")

        finally:
            if grabber:
                try:
                    if grabber.is_streaming:
                        grabber.stream_stop()
                    if grabber.is_device_open:
                        grabber.device_close()
                except Exception:
                    pass
            log.info("Camera thread finished.")

    def stop(self):
        self._mutex.lock()
        self._stop_requested = True
        self._mutex.unlock()
