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
        self._running_mutex = QMutex()
        self._stop_requested = False

        self.desired_width = 640
        self.desired_height = 480
        self.desired_pixel_format = "Mono8"

    def run(self):
        self._stop_requested = False
        log.info(
            f"SDKCameraThread started (FPS={self.target_fps}, Exp={self.exposure_us}µs)"
        )

        try:
            ic4.Library.init()

            devices = ic4.DeviceEnum.devices()
            if not devices:
                raise RuntimeError("No TIS cameras found")
            dev_info = devices[0]
            log.info(f"Using camera: {dev_info.model_name} (S/N {dev_info.serial})")

            grabber = ic4.Grabber()
            grabber.device_open(dev_info)
            log.info("Camera opened.")
            pm = grabber.device_property_map

            # Continuous free‐run, no triggers
            for pid, val in (
                (ic4.PropId.ACQUISITION_MODE, "Continuous"),
                (ic4.PropId.TRIGGER_MODE, "Off"),
            ):
                try:
                    pm.set_value(pid, val)
                except ic4.IC4Exception as e:
                    log.warning(f"Couldn’t set {pid}: {e}")

            # Pixel format, size, exposure
            current_fmt = pm.get_value_str(ic4.PropId.PIXEL_FORMAT)
            if current_fmt != self.desired_pixel_format:
                pm.set_value(ic4.PropId.PIXEL_FORMAT, self.desired_pixel_format)
                log.info(f"Pixel format → {self.desired_pixel_format}")

            for pid, val in (
                (ic4.PropId.WIDTH, self.desired_width),
                (ic4.PropId.HEIGHT, self.desired_height),
                (ic4.PropId.EXPOSURE_TIME, self.exposure_us),
            ):
                pm.set_value(pid, val)
                log.info(f"{pid.name} → {val}")

            sink = ic4.SnapSink()
            grabber.stream_setup(
                sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            log.info("Acquisition started.")

            # Main loop
            while not self._stop_requested:
                try:
                    to_ms = max(int(1000 / self.target_fps * 2), 100)
                    buf = sink.snap_single(timeout_ms=to_ms)
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
                            qfmt = QImage.Format_RGB888
                            img = QImage(frame.data, w, h, bpl, qfmt)
                        else:
                            # Qt versions <5.10 may lack Format_BGR888
                            if hasattr(QImage, "Format_BGR888"):
                                img = QImage(
                                    frame.data, w, h, bpl, QImage.Format_BGR888
                                )
                            else:
                                conv = frame[..., ::-1].copy()
                                img = QImage(conv.data, w, h, bpl, QImage.Format_RGB888)
                    else:
                        log.warning(f"Unsupported format {fmt} or shape {frame.shape}")
                        continue

                    self.frame_ready.emit(img.copy(), frame.copy())
                    del buf

                except ic4.IC4Exception as ic_err:
                    if ic_err.code == ic4.ErrorCode.Timeout:
                        continue
                    msg = f"Snap Error: {ic_err}"
                    log.error(msg)
                    self.camera_error.emit(msg, str(ic_err.code))
                    break

        except Exception as e:
            msg = str(e)
            log.error(f"Camera thread error: {msg}", exc_info=True)
            self.camera_error.emit(msg, "THREAD_ERROR")

        finally:
            # Clean up
            try:
                if grabber and grabber.is_streaming:
                    grabber.stream_stop()
                if grabber and grabber.is_device_open:
                    grabber.device_close()
            except Exception as cleanup_err:
                log.warning(f"Cleanup error: {cleanup_err}")
            ic4.Library.exit()
            log.info("SDKCameraThread finished.")

    def stop(self):
        log.info("Stop requested for camera thread.")
        self._running_mutex.lock()
        self._stop_requested = True
        self._running_mutex.unlock()
