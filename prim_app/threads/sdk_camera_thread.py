# File: prim_app/threads/sdk_camera_thread.py

import logging
import imagingcontrol4 as ic4
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    # emitted when grabber is open & ready (so UI can build controls, if needed)
    grabber_ready = pyqtSignal()

    # emitted for each new frame: (QImage, raw_buffer_object)
    frame_ready = pyqtSignal(QImage, object)

    # emitted on error: (message, code_as_string)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None, desired_fps=10):
        super().__init__(parent)
        self.grabber = None
        self._stop_requested = False
        self._desired_fps = desired_fps

    def run(self):
        try:
            # ─── 1) Initialize the IC4 library (each thread must do this exactly once) ──
            ic4.Library.init(
                api_log_level=ic4.LogLevel.INFO,
                log_targets=ic4.LogTarget.STDERR,
            )
            log.info("SDKCameraThread: Library.init() succeeded.")

            # ─── 2) Enumerate all connected cameras, pick the first one ─────────────────
            device_list = ic4.DeviceEnum.devices()
            if not device_list:
                raise RuntimeError("No IC4 camera devices found on this machine.")
            dev_info = device_list[0]
            log.info(
                f"SDKCameraThread: selected device = {dev_info.model_name!r}, "
                f"S/N={dev_info.serial!r}"
            )

            # ─── 3) Open that device on a new Grabber ───────────────────────────────────
            self.grabber = ic4.Grabber()
            self.grabber.device_open(dev_info)

            # ─── 4) Force “Continuous” mode if possible ─────────────────────────────────
            acq_mode_node = self.grabber.device_property_map.find_enumeration(
                "AcquisitionMode"
            )
            if acq_mode_node:
                all_modes = [entry.name for entry in acq_mode_node.entries]
                if "Continuous" in all_modes:
                    acq_mode_node.value = "Continuous"
                else:
                    acq_mode_node.value = all_modes[0]

            # ─── 5) AUTOMATICALLY FIND THE “BEST” MONOCHROME FORMAT ─────────────────────
            best_pf = None
            best_width = 0
            best_height = 0
            pf_node = self.grabber.device_property_map.find_enumeration("PixelFormat")
            if pf_node:
                # 5a) Prefer Mono8 entries first
                mono8_entries = [e for e in pf_node.entries if "Mono8" in e.name]
                if mono8_entries:
                    for entry in mono8_entries:
                        try:
                            pf_node.value = entry.name
                            w_node = self.grabber.device_property_map.find_integer(
                                "Width"
                            )
                            h_node = self.grabber.device_property_map.find_integer(
                                "Height"
                            )
                            if w_node and h_node:
                                w = int(w_node.value)
                                h = int(h_node.value)
                                if (w * h) > (best_width * best_height):
                                    best_width = w
                                    best_height = h
                                    best_pf = entry.name
                        except Exception as e:
                            log.warning(f"Skipping PF={entry.name} due to error: {e}")
                            continue

                # 5b) If no Mono8, look for Mono10 or Mono16
                if best_pf is None:
                    for entry in pf_node.entries:
                        name = entry.name
                        if "Mono10" in name or "Mono16" in name:
                            try:
                                pf_node.value = name
                                w_node = self.grabber.device_property_map.find_integer(
                                    "Width"
                                )
                                h_node = self.grabber.device_property_map.find_integer(
                                    "Height"
                                )
                                if w_node and h_node:
                                    w = int(w_node.value)
                                    h = int(h_node.value)
                                    if (w * h) > (best_width * best_height):
                                        best_width = w
                                        best_height = h
                                        best_pf = name
                            except Exception as e:
                                log.warning(f"Skipping PF={name} due to error: {e}")
                                continue

            if best_pf is None:
                raise RuntimeError(
                    "Could not find any usable Mono8, Mono10, or Mono16 format."
                )

            # ─── 6) Now set the device to that “best” pixel format and resolution:
            log.info(
                f"SDKCameraThread: picked PF={best_pf!r} at W×H={best_width}×{best_height}"
            )
            try:
                pf_node.value = best_pf
            except Exception as e:
                raise RuntimeError(f"Failed to set PixelFormat={best_pf}: {e}")

            # Re‐read actual W×H in case the camera clamps dimensions
            w_node = self.grabber.device_property_map.find_integer("Width")
            h_node = self.grabber.device_property_map.find_integer("Height")
            actual_w, actual_h = int(w_node.value), int(h_node.value)
            log.info(f"Camera reports W×H after setting PF: {actual_w}×{actual_h}")

            # ─── 7) TRY TO SET AcquisitionFrameRate = desired FPS (if that node exists) ──
            fr_node = self.grabber.device_property_map.find_float(
                "AcquisitionFrameRate"
            )
            if fr_node:
                try:
                    fr_node.value = float(self._desired_fps)
                    log.info(
                        f"SDKCameraThread: forced AcquisitionFrameRate = {self._desired_fps}"
                    )
                except Exception as e:
                    log.warning(
                        f"SDKCameraThread: could not set AcquisitionFrameRate "
                        f"to {self._desired_fps}: {e}"
                    )

            # ─── 8) BUILD a QueueSink that requests Mono8 if possible ───────────────────
            # First try requesting Mono8 directly
            try:
                sink = ic4.QueueSink(
                    self, [ic4.PixelFormat.Mono8], max_output_buffers=1
                )
            except Exception:
                # Fallback: use the camera’s native best_pf (Mono10p or Mono16)
                sink = ic4.QueueSink(
                    self, [ic4.PixelFormat[best_pf]], max_output_buffers=1
                )

            self.grabber.stream_setup(sink)
            self.grabber_ready.emit()

            # ─── 9) START STREAMING ─────────────────────────────────────────────────────
            self.grabber.stream_start()
            log.info(
                "SDKCameraThread: stream_start() succeeded. Entering frame loop..."
            )

            # ─── 10) BUSY-LOOP, POPPING FRAMES until stop() is called ───────────────────
            while not self._stop_requested:
                ic4.sleep(10)  # around 10 ms sleep (≈100 FPS spin-loop)

            # ─── 11) STOP STREAMING & CLOSE DEVICE ─────────────────────────────────────
            self.grabber.stream_stop()
            self.grabber.device_close()
            log.info("SDKCameraThread: streaming stopped, device closed.")

        except Exception as e:
            # Convert e.code (an ErrorCode enum) to string
            msg = str(e)
            code_enum = getattr(e, "code", "")
            code_str = str(code_enum) if code_enum else ""
            log.exception("SDKCameraThread: encountered an error in run().")
            self.error.emit(msg, code_str)

        finally:
            # ─── 12) CLEAN UP: call Library.exit() exactly once per thread ──────────────
            try:
                ic4.Library.exit()
                log.info("SDKCameraThread: Library.exit() called.")
            except Exception:
                pass

    def stop(self):
        self._stop_requested = True

    # ← This is the callback from QueueSink when a new frame arrives
    def frames_queued(self, sink):
        try:
            buf = sink.pop_output_buffer()
            arr = (
                buf.numpy_wrap()
            )  # shape might be (H, W, 1) with dtype=uint8 or uint16

            # Remove the singleton channel dimension if present: shape → (H, W)
            if arr.ndim == 3 and arr.shape[2] == 1:
                gray = arr[:, :, 0]
            else:
                gray = arr  # In case it already is (H, W)

            # If dtype is >8 bits, downscale to 8-bit
            if gray.dtype != np.uint8:
                max_val = float(gray.max()) if gray.max() > 0 else 1.0
                scale = 255.0 / max_val
                gray8 = (gray.astype(np.float32) * scale).astype(np.uint8)
            else:
                gray8 = gray

            h, w = gray8.shape[:2]

            # Build a QImage from single-channel grayscale
            qimg = QImage(
                gray8.data,
                w,
                h,
                gray8.strides[0],
                QImage.Format_Grayscale8,
            )

            self.frame_ready.emit(qimg, buf)

        except Exception as e:
            log.error(
                f"SDKCameraThread.frames_queued: Error popping/converting buffer: {e}"
            )
            code_enum = getattr(e, "code", "")
            code_str = str(code_enum) if code_enum else ""
            self.error.emit(str(e), code_str)
        finally:
            # With max_output_buffers=1, IC4 automatically recycles the buffer.
            pass
