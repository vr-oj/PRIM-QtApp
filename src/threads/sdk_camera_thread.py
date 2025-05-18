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

        # capture settings
        self.desired_width = width
        self.desired_height = height
        self.desired_pixel_format = pixel_format
        self.desired_exposure = exposure_us
        self.desired_gain = None
        self.desired_brightness = None
        self.desired_auto_exposure = None

        # pending updates
        self._pending_exposure = None
        self._pending_gain = None
        self._pending_brightness = None
        self._pending_auto_exposure = None

    def update_exposure(self, new_exp_us: int):
        self._pending_exposure = new_exp_us

    def update_gain(self, new_gain: int):
        self._pending_gain = new_gain

    def update_brightness(self, new_brightness: int):
        self._pending_brightness = new_brightness

    def update_auto_exposure(self, enable: bool):
        self._pending_auto_exposure = enable

    def run(self):
        self._stop_requested = False
        log.info(
            f"Camera thread start (FPS={self.target_fps}, Exp={self.desired_exposure}µs)"
        )
        grabber = None

        try:
            # ─── open camera ───────────────────────────────────
            devices = ic4.DeviceEnum.devices()
            if not devices:
                raise RuntimeError("No TIS cameras found")
            dev = devices[0]
            log.info(f"Using {dev.model_name} (S/N {dev.serial})")

            grabber = ic4.Grabber()
            grabber.device_open(dev)
            log.info("Camera opened.")
            pm = grabber.device_property_map

            # ─── enumerate resolutions ──────────────────────────
            try:
                wprop = pm.find(ic4.PropId.WIDTH)
                hprop = pm.find(ic4.PropId.HEIGHT)
                if isinstance(wprop, PropInteger) and isinstance(hprop, PropInteger):
                    modes = [
                        f"{w}x{h}"
                        for w in range(
                            wprop.minimum, wprop.maximum + 1, wprop.increment
                        )
                        for h in range(
                            hprop.minimum, hprop.maximum + 1, hprop.increment
                        )
                    ]
                    self.camera_resolutions_available.emit(modes)
            except Exception as e:
                log.warning(f"Couldn’t enumerate resolutions: {e}")

            # ─── emit initial control properties ────────────────
            controls = {}

            def try_prop(name, pid):
                try:
                    prop = pm.find(pid)
                    # ADD THIS DEBUG LOG:
                    log.debug(
                        f"For property '{name}' (ID: {str(pid)}), found prop: {prop} of type {type(prop)}"
                    )

                    if isinstance(prop, PropInteger):
                        controls[name] = {
                            "enabled": True,
                            "min": prop.minimum,
                            "max": prop.maximum,
                            "value": prop.get(),
                        }
                    elif name == "auto_exposure" and isinstance(prop, PropBoolean):
                        controls[name] = {
                            "enabled": True,
                            "value": prop.get() != 0,
                            "is_auto_on": prop.get() != 0,
                            "min": 0,
                            "max": 1,
                        }
                    else:  # ADD THIS ELSE BLOCK
                        log.warning(
                            f"Property '{name}' (ID: {str(pid)}) is of unexpected type: {type(prop)} or not processed correctly. Prop value: {prop}"
                        )

                except Exception as e:  # ENSURE THIS MODIFICATION IS PRESENT
                    log.warning(
                        f"Exception getting property {name} (ID: {str(pid)}): {e}",
                        exc_info=True,
                    )

            # always try exposure & gain
            try_prop("exposure", ic4.PropId.EXPOSURE_TIME)
            try_prop("gain", ic4.PropId.GAIN)
            # optional brightness
            if hasattr(ic4.PropId, "BRIGHTNESS"):
                try_prop("brightness", ic4.PropId.BRIGHTNESS)
            # optional auto-exposure
            if hasattr(ic4.PropId, "AUTO_EXPOSURE"):
                try_prop("auto_exposure", ic4.PropId.AUTO_EXPOSURE)

            # placeholder ROI
            roi = {"max_w": 0, "max_h": 0, "x": 0, "y": 0, "w": 0, "h": 0}

            log.info(
                f"Emitting camera_properties_available: controls={controls}, roi={roi}"
            )
            self.camera_properties_available.emit({"controls": controls, "roi": roi})

            # ─── configure free-run mode ────────────────────────
            for pid, val in (
                (ic4.PropId.ACQUISITION_MODE, "Continuous"),
                (ic4.PropId.TRIGGER_MODE, "Off"),
            ):
                try:
                    pm.set_value(pid, val)
                except Exception as e:
                    log.warning(f"Couldn’t set {pid.name}: {e}")

            # ─── set pixel-format, size, exposure ───────────────
            if pm.get_value_str(ic4.PropId.PIXEL_FORMAT) != self.desired_pixel_format:
                pm.set_value(ic4.PropId.PIXEL_FORMAT, self.desired_pixel_format)
            pm.set_value(ic4.PropId.WIDTH, self.desired_width)
            pm.set_value(ic4.PropId.HEIGHT, self.desired_height)
            pm.set_value(ic4.PropId.EXPOSURE_TIME, self.desired_exposure)

            sink = ic4.SnapSink()
            grabber.stream_setup(
                sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            log.info("Acquisition started.")

            # ─── grab loop ───────────────────────────────────────
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
                    except Exception as e:
                        log.warning(f"Failed to set exposure: {e}")
                    finally:
                        self._pending_exposure = None

                # apply pending gain
                if self._pending_gain is not None:
                    try:
                        pm.set_value(ic4.PropId.GAIN, self._pending_gain)
                        log.info(f"Gain set to {self._pending_gain}")
                        self.desired_gain = self._pending_gain
                    except Exception as e:
                        log.warning(f"Failed to set gain: {e}")
                    finally:
                        self._pending_gain = None

                # apply pending brightness if supported
                if self._pending_brightness is not None and hasattr(
                    ic4.PropId, "BRIGHTNESS"
                ):
                    try:
                        pm.set_value(ic4.PropId.BRIGHTNESS, self._pending_brightness)
                        log.info(f"Brightness set to {self._pending_brightness}")
                        self.desired_brightness = self._pending_brightness
                    except Exception as e:
                        log.warning(f"Failed to set brightness: {e}")
                    finally:
                        self._pending_brightness = None

                # apply pending auto-exposure if supported
                if self._pending_auto_exposure is not None and hasattr(
                    ic4.PropId, "AUTO_EXPOSURE"
                ):
                    try:
                        # boolean prop: On/Off
                        val = "On" if self._pending_auto_exposure else "Off"
                        pm.set_value(ic4.PropId.AUTO_EXPOSURE, val)
                        log.info(f"Auto‐Exposure set to {val}")
                        self.desired_auto_exposure = self._pending_auto_exposure
                    except Exception as e:
                        log.warning(f"Failed to set auto‐exposure: {e}")
                    finally:
                        self._pending_auto_exposure = None

                # snap a frame
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
