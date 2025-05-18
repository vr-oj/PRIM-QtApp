import logging
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal, QMutex
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    frame_ready = pyqtSignal(QImage, object)
    camera_error = pyqtSignal(str, str)
    camera_resolutions_available = pyqtSignal(list)

    def __init__(
        self, exposure_us=20000, target_fps=20, width=640, height=480, parent=None
    ):
        super().__init__(parent)
        self.exposure_us = exposure_us
        self.target_fps = target_fps
        self._stop_requested = False
        self._mutex = QMutex()
        # Desired capture settings (now passed in)
        self.desired_width = width
        self.desired_height = height

    def run(self):
        self._stop_requested = False
        log.info(
            f"Camera thread start (FPS={self.target_fps}, Exp={self.exposure_us}µs)"
        )

        try:
            # 1) Discover camera
            devices = ic4.DeviceEnum.devices()
            if not devices:
                raise RuntimeError("No TIS cameras found")
            dev = devices[0]
            log.info(f"Using {dev.model_name} (S/N {dev.serial})")

            # 2) Open
            grabber = ic4.Grabber()
            grabber.device_open(dev)
            log.info("Camera opened.")
            pm = grabber.device_property_map
            # ── enumerate valid widths & heights ───────────────────
            try:
                wprop = pm.find(ic4.PropId.WIDTH)
                hprop = pm.find(ic4.PropId.HEIGHT)
                # only if they’re integer‐type props
                from imagingcontrol4.properties import PropInteger

                if isinstance(wprop, PropInteger) and isinstance(hprop, PropInteger):
                    widths = list(
                        range(wprop.minimum, wprop.maximum + 1, wprop.increment)
                    )
                    heights = list(
                        range(hprop.minimum, hprop.maximum + 1, hprop.increment)
                    )
                    # cross‐product into "WxH" strings
                    modes = [f"{w}x{h}" for w in widths for h in heights]
                    self.camera_resolutions_available.emit(modes)
            except Exception as e:
                log.warning(f"Couldn’t enumerate resolutions: {e}")

            # 3) Configure free-run
            for pid, val in (
                (ic4.PropId.ACQUISITION_MODE, "Continuous"),
                (ic4.PropId.TRIGGER_MODE, "Off"),
            ):
                try:
                    pm.set_value(pid, val)
                except ic4.IC4Exception as e:
                    log.warning(f"Couldn’t set {pid.name}: {e}")

            # 4) Pixel format, size, exposure
            fmt = pm.get_value_str(ic4.PropId.PIXEL_FORMAT)
            if fmt != self.desired_pixel_format:
                pm.set_value(ic4.PropId.PIXEL_FORMAT, self.desired_pixel_format)
            for pid, v in (
                (ic4.PropId.WIDTH, self.desired_width),
                (ic4.PropId.HEIGHT, self.desired_height),
                (ic4.PropId.EXPOSURE_TIME, self.exposure_us),
            ):
                pm.set_value(pid, v)

            # 5) Start streaming
            sink = ic4.SnapSink()
            grabber.stream_setup(
                sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )

            # 6) Capture loop
            while True:
                self._mutex.lock()
                stop = self._stop_requested
                self._mutex.unlock()
                if stop:
                    break

                try:
                    timeout = max(int(1000 / self.target_fps * 2), 100)
                    buf = sink.snap_single(timeout_ms=timeout)
                    frame = buf.numpy_copy()
                    h, w = frame.shape[:2]

                    fmt = pm.get_value_str(ic4.PropId.PIXEL_FORMAT)
                    # monochrome two-dim or 3-dim with channel=1
                    if frame.ndim == 2 or (frame.ndim == 3 and frame.shape[2] == 1):
                        gray = frame if frame.ndim == 2 else frame[..., 0]
                        img = QImage(gray.data, w, h, w, QImage.Format_Grayscale8)
                    # packed RGB/BGR
                    elif (
                        fmt in ("RGB8", "BGR8")
                        and frame.ndim == 3
                        and frame.shape[2] == 3
                    ):
                        bpl = w * 3
                        if fmt == "RGB8":
                            img = QImage(frame.data, w, h, bpl, QImage.Format_RGB888)
                        else:
                            # fallback if no Format_BGR888
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
            # always stop and close
            try:
                if grabber and grabber.is_streaming:
                    grabber.stream_stop()
                if grabber and grabber.is_device_open:
                    grabber.device_close()
            except Exception as cleanup:
                log.warning(f"Cleanup failed: {cleanup}")
            log.info("Camera thread finished.")

    def stop(self):
        self._mutex.lock()
        self._stop_requested = True
        self._mutex.unlock()
