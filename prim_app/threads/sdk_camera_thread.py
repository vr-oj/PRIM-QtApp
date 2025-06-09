# File: prim_app/threads/sdk_camera_thread.py

import logging
import time
import imagingcontrol4 as ic4
import numpy as np

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)

FPS_LOG_INTERVAL_S = 5.0  # seconds between FPS log messages


class SDKCameraThread(QThread):
    grabber_ready = pyqtSignal()
    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grabber = None
        self._stop_requested = False
        self._device_info = None
        self._resolution = None
        self._sink = None
        self._frame_counter = 0
        self._fps_start_time = None

    def set_device_info(self, dev_info):
        self._device_info = dev_info

    def set_resolution(self, resolution_tuple):
        self._resolution = resolution_tuple

    def run(self):
        try:
            try:
                ic4.Library.init(
                    api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR
                )
                log.info("SDKCameraThread: Library.init() succeeded.")
            except RuntimeError as e:
                if "already called" in str(e):
                    log.info("SDKCameraThread: IC4 already initialized; continuing.")
                else:
                    raise

            if self._device_info is None:
                raise RuntimeError("No DeviceInfo passed to SDKCameraThread.")

            self.grabber = ic4.Grabber()
            self.grabber.device_open(self._device_info)
            log.info(
                f"SDKCameraThread: device_open() succeeded for '{self._device_info.model_name}' (S/N '{self._device_info.serial}')."
            )

            if self._resolution is not None:
                w, h, pf_name = self._resolution
                try:
                    pf_node = self.grabber.device_property_map.find_enumeration(
                        "PixelFormat"
                    )
                    if pf_node:
                        pf_node.value = pf_name
                        log.info(f"SDKCameraThread: Set PixelFormat = {pf_name}")
                        w_node = self.grabber.device_property_map.find_integer("Width")
                        h_node = self.grabber.device_property_map.find_integer("Height")
                        if w_node and h_node:
                            w_node.value = w
                            h_node.value = h
                            log.info(f"SDKCameraThread: Set resolution = {w}×{h}")
                    else:
                        log.warning(
                            "SDKCameraThread: PixelFormat node not found; using default."
                        )
                except Exception as e:
                    log.warning(f"SDKCameraThread: Could not set resolution/PF: {e}")

            try:
                acq_node = self.grabber.device_property_map.find_enumeration(
                    "AcquisitionMode"
                )
                if acq_node:
                    entries = [e.name for e in acq_node.entries]
                    if "Continuous" in entries:
                        acq_node.value = "Continuous"
                        log.info("SDKCameraThread: Set AcquisitionMode = Continuous")
                    else:
                        acq_node.value = entries[0]
                        log.info(f"SDKCameraThread: Set AcquisitionMode = {entries[0]}")
            except Exception as e:
                log.warning(f"SDKCameraThread: Could not set AcquisitionMode: {e}")

            try:
                trig_node = self.grabber.device_property_map.find_enumeration(
                    "TriggerMode"
                )
                if trig_node:
                    trig_node.value = "Off"
                    log.info("SDKCameraThread: Set TriggerMode = Off")
                else:
                    log.warning(
                        "SDKCameraThread: TriggerMode node not found; assuming free‐run."
                    )
            except Exception as e:
                log.warning(f"SDKCameraThread: Could not disable TriggerMode: {e}")

            # ─── Disable Auto Exposure ─────────────────────────────────────────
            try:
                ae_node = self.grabber.device_property_map.find_enumeration(
                    "ExposureAuto"
                )
                if ae_node:
                    ae_node.value = "Off"
                    log.info("SDKCameraThread: Set ExposureAuto = Off")
            except Exception as e:
                log.warning(f"SDKCameraThread: Could not disable auto exposure: {e}")

            # ─── Set ExposureTime before AcquisitionFrameRate ─────────────────
            try:
                exp_node = self.grabber.device_property_map.find_float("ExposureTime")
                if exp_node and not exp_node.is_readonly and exp_node.is_available:
                    exp_node.value = 5000.0  # 5 ms
                    log.info(f"SDKCameraThread: Set ExposureTime = {exp_node.value}")
                else:
                    log.warning(
                        "SDKCameraThread: Exposure control not available or readonly."
                    )
            except Exception as e:
                log.warning(f"SDKCameraThread: Could not set ExposureTime: {e}")

            try:
                fr_node = self.grabber.device_property_map.find_float(
                    "AcquisitionFrameRate"
                )
                if fr_node and not fr_node.is_readonly and fr_node.is_available:
                    fr_node.value = 10.0
                    log.info(
                        f"SDKCameraThread: Set AcquisitionFrameRate = {fr_node.value}"
                    )
                else:
                    log.warning(
                        "SDKCameraThread: FPS control not available or readonly."
                    )
            except Exception as e:
                log.warning(f"SDKCameraThread: Could not set AcquisitionFrameRate: {e}")

            self.grabber_ready.emit()

            try:
                self._sink = ic4.QueueSink(
                    self, [ic4.PixelFormat.Mono8], max_output_buffers=16
                )
            except:
                native_pf = self._resolution[2] if self._resolution else None
                if native_pf and hasattr(ic4.PixelFormat, native_pf):
                    self._sink = ic4.QueueSink(
                        self,
                        [getattr(ic4.PixelFormat, native_pf)],
                        max_output_buffers=16,
                    )
                else:
                    raise RuntimeError(
                        "SDKCameraThread: Unable to create QueueSink for Mono8 or native PF."
                    )

            from imagingcontrol4 import StreamSetupOption

            self.grabber.stream_setup(
                self._sink,
                setup_option=StreamSetupOption.ACQUISITION_START,
            )
            self._frame_counter = 0
            self._fps_start_time = time.time()
            log.info(
                "SDKCameraThread: stream_setup(ACQUISITION_START) succeeded. Entering frame loop…"
            )

            while not self._stop_requested:
                self.msleep(10)

            self.grabber.stream_stop()
            self.grabber.device_close()
            log.info("SDKCameraThread: Streaming stopped, device closed.")

        except Exception as e:
            msg = str(e)
            code_enum = getattr(e, "code", None)
            code_str = str(code_enum) if code_enum else ""
            log.exception("SDKCameraThread: encountered an error.")
            self.error.emit(msg, code_str)

        finally:
            try:
                ic4.Library.exit()
                log.info("SDKCameraThread: Library.exit() called.")
                import imagingcontrol4.library as ic4lib

                ic4lib.Library._core = None
            except Exception:
                pass

    def frames_queued(self, sink):
        try:
            buf = sink.pop_output_buffer()
            self._frame_counter += 1
            arr = buf.numpy_wrap()

            if arr.dtype == np.uint8:
                gray8 = arr
            else:
                max_val = float(arr.max()) if arr.max() > 0 else 1.0
                scale = 255.0 / max_val
                gray8 = (arr.astype(np.float32) * scale).astype(np.uint8)

            h, w = gray8.shape[:2]
            qimg = QImage(gray8.data, w, h, gray8.strides[0], QImage.Format_Grayscale8)
            self.frame_ready.emit(qimg, buf)

            if self._fps_start_time is not None:
                elapsed = time.time() - self._fps_start_time
                if elapsed >= FPS_LOG_INTERVAL_S:
                    fps = self._frame_counter / elapsed if elapsed > 0 else 0.0
                    log.info("SDKCameraThread: Actual FPS = %.2f", fps)
                    self._frame_counter = 0
                    self._fps_start_time = time.time()

        except Exception as e:
            log.error(
                f"SDKCameraThread.frames_queued: Error popping/converting buffer: {e}"
            )
            code_enum = getattr(e, "code", None)
            code_str = str(code_enum) if code_enum else ""
            self.error.emit(str(e), code_str)

    def sink_connected(self, sink, pixel_format, min_buffers_required) -> bool:
        return True

    def sink_disconnected(self, sink) -> None:
        pass

    def stop(self):
        self._stop_requested = True
