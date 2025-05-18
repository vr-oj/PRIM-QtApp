import logging
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal, QMutex
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    frame_ready = pyqtSignal(QImage, object)
    camera_error = pyqtSignal(str, str)

    def __init__(self, exposure_us=20000, target_fps=20, parent=None):
        super().__init__(parent)
        self.exposure_us = exposure_us
        self.target_fps = target_fps
        self._stop_requested = False
        self._mutex = QMutex()
        # Desired capture settings
        self.desired_width = 640
        self.desired_height = 480
        self.desired_pixel_format = "Mono8"

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

            # --- QUICK SANITY CHECK: try to grab one frame with a long timeout
            try:
                log.info("Attempting initial snap (2 s timeout)…")
                buf0 = sink.snap_single(timeout_ms=2000)
                frame0 = buf0.numpy_copy()
                log.info(f"✅ Got first frame: shape={frame0.shape}")
                # emit it to clear the “Connecting…” text right away
                h0, w0 = frame0.shape[:2]
                q0 = QImage(
                    frame0.data,
                    w0,
                    h0,
                    w0,
                    (
                        QImage.Format_Grayscale8
                        if frame0.ndim == 2
                        else QImage.Format_RGB888
                    ),
                )
                self.frame_ready.emit(q0.copy(), frame0.copy())
                del buf0
            except ic4.IC4Exception as e0:
                log.error(f"⛔ Initial snap failed: {e0.code} – {e0}")
                # if it’s a timeout, we’ll still enter the loop below once
                if e0.code != ic4.ErrorCode.Timeout:
                    self.camera_error.emit(f"Init Snap Error: {e0}", str(e0.code))
                    return

            log.info("Acquisition started, entering continuous grab loop.")

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
                    if fmt in ("Mono8", "Y800") and frame.ndim == 2:
                        img = QImage(frame.data, w, h, w, QImage.Format_Grayscale8)
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
