# File: prim_app/threads/sdk_camera_thread.py

import logging
import imagingcontrol4 as ic4
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    grabber_ready = pyqtSignal()
    frame_ready = pyqtSignal(QImage, object)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None, desired_fps=10):
        super().__init__(parent)
        self.grabber = None
        self._stop_requested = False
        self._desired_fps = desired_fps

    def run(self):
        try:
            # ─── Initialize IC4 ───────────────────────────────────────
            ic4.Library.init(
                api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR
            )
            log.info("SDKCameraThread: Library.init() succeeded.")

            # ─── Enumerate Cameras ─────────────────────────────────────
            device_list = ic4.DeviceEnum.devices()
            if not device_list:
                raise RuntimeError("No IC4 camera devices found on this machine.")
            dev_info = device_list[0]
            log.info(
                f"Selected device = {dev_info.model_name!r}, S/N={dev_info.serial!r}"
            )

            # ─── Open Grabber ──────────────────────────────────────────
            self.grabber = ic4.Grabber()
            self.grabber.device_open(dev_info)

            # ─── Force Continuous Mode ─────────────────────────────────
            acq_mode_node = self.grabber.device_property_map.find_enumeration(
                "AcquisitionMode"
            )
            if acq_mode_node:
                all_modes = [entry.name for entry in acq_mode_node.entries]
                if "Continuous" in all_modes:
                    acq_mode_node.value = "Continuous"
                else:
                    acq_mode_node.value = all_modes[0]

            # ─── Choose “Best” Monochrome PixelFormat ───────────────────
            best_pf = None
            best_width = 0
            best_height = 0

            pf_node = self.grabber.device_property_map.find_enumeration("PixelFormat")
            if pf_node:
                # First, look for a direct Mono8 entry (highest priority)
                mono8_entries = [e for e in pf_node.entries if "Mono8" in e.name]
                if mono8_entries:
                    # If there are multiple Mono8 entries at different resolutions, pick the largest:
                    for entry in mono8_entries:
                        pf_node.value = entry.name
                        w_node = self.grabber.device_property_map.find_integer("Width")
                        h_node = self.grabber.device_property_map.find_integer("Height")
                        if w_node and h_node:
                            w, h = int(w_node.value), int(h_node.value)
                            if (w * h) > (best_width * best_height):
                                best_width, best_height = w, h
                                best_pf = entry.name
                else:
                    # If no “Mono8”, consider Mono10 or Mono16—pick whichever yields largest area:
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
                                    w, h = int(w_node.value), int(h_node.value)
                                    if (w * h) > (best_width * best_height):
                                        best_width, best_height = w, h
                                        best_pf = name
                            except Exception:
                                continue

            if best_pf is None:
                raise RuntimeError("Could not find any Mono8/Mono10/Mono16 format.")

            # ─── Apply the Chosen Format & Resolution ────────────────────
            log.info(f"Picked PF={best_pf!r} at W×H={best_width}×{best_height}")
            pf_node.value = best_pf

            # Re‐read actual W×H (in case the camera clamps to multiples of 8, etc.)
            w_node = self.grabber.device_property_map.find_integer("Width")
            h_node = self.grabber.device_property_map.find_integer("Height")
            actual_w, actual_h = int(w_node.value), int(h_node.value)
            log.info(f"Camera reports W×H after setting PF: {actual_w}×{actual_h}")

            # ─── Try to Set Desired FPS ──────────────────────────────────
            fr_node = self.grabber.device_property_map.find_float(
                "AcquisitionFrameRate"
            )
            if fr_node:
                try:
                    fr_node.value = float(self._desired_fps)
                    log.info(f"Forced AcquisitionFrameRate = {self._desired_fps}")
                except Exception as e:
                    log.warning(
                        f"Could not set AcquisitionFrameRate to {self._desired_fps}: {e}"
                    )

            # ─── Build a QueueSink for Mono‐format (we’ll request 8‐bit output if possible) ───
            # If the camera can produce 8‐bit Mono directly, we’ll request that. Otherwise, the camera may
            # give us a 10‐bit or 16‐bit buffer, which we’ll downscale in frames_queued().

            # We specifically ask IC4 to hand us pixel buffers of type MONO8 if available:
            #   - If the chosen PF is Mono8, this will succeed.
            #   - If the chosen PF is Mono10/Mono16, IC4 might automatically downconvert to 8‐bit if possible,
            #     but if not, we will receive higher‐bit buffers and convert ourselves.
            try:
                sink = ic4.QueueSink(
                    self, [ic4.PixelFormat.Mono8], max_output_buffers=1
                )
            except Exception:
                # Fallback: request the camera’s native PF (best_pf). IC4 may only give us raw Mono10/Mono16.
                sink = ic4.QueueSink(
                    self, [ic4.PixelFormat[best_pf]], max_output_buffers=1
                )

            self.grabber.stream_setup(sink)
            self.grabber_ready.emit()

            # ─── Start Streaming ──────────────────────────────────────────
            self.grabber.stream_start()
            log.info(
                "SDKCameraThread: stream_start() succeeded. Entering frame loop..."
            )

            while not self._stop_requested:
                ic4.sleep(10)  # ~10 ms

            # ─── Stop and Close ───────────────────────────────────────────
            self.grabber.stream_stop()
            self.grabber.device_close()
            log.info("SDKCameraThread: streaming stopped, device closed.")

        except Exception as e:
            log.exception("SDKCameraThread: encountered an error in run().")
            msg = str(e)
            code = getattr(e, "code", "")
            self.error.emit(msg, code)

        finally:
            try:
                ic4.Library.exit()
                log.info("SDKCameraThread: Library.exit() called.")
            except Exception:
                pass

    def stop(self):
        self._stop_requested = True

    def frames_queued(self, sink):
        try:
            buf = sink.pop_output_buffer()
            arr = (
                buf.numpy_wrap()
            )  # Could be dtype=uint8, uint16, or uint32 depending on PF

            # Determine bit depth and downscale to 8-bit if needed
            # 1) If arr.dtype == uint8 → we already have Mono8
            # 2) If arr.dtype == uint16 → camera likely gave Mono10 or Mono16; we scale down to 0–255
            if arr.dtype == np.uint8:
                gray8 = arr  # shape=(H, W), dtype=uint8
            else:
                # Convert 10/16‐bit to 8‐bit by right‐shifting (or dividing).
                # For Mono10, values are 0–1023. For Mono16 (0–65535). We can simply divide:
                max_val = float(arr.max())  # e.g. 1023 or 65535
                if max_val > 0:
                    scale = 255.0 / max_val
                    gray8 = (arr.astype(np.float32) * scale).astype(np.uint8)
                else:
                    gray8 = (arr >> 8).astype(np.uint8)  # fallback bitshift

            h, w = gray8.shape[:2]

            # Build a QImage from single‐channel grayscale data
            # QImage.Format_Grayscale8 expects one byte per pixel (no palette).
            qimg = QImage(
                gray8.data,
                w,
                h,
                gray8.strides[0],
                QImage.Format_Grayscale8,
            )

            # Emit QImage plus the raw buffer, so UI can also re‐use buf if needed
            self.frame_ready.emit(qimg, buf)

        except Exception as e:
            log.error(f"frames_queued: Error popping or converting buffer: {e}")
            self.error.emit(str(e), "")
        finally:
            # With max_output_buffers=1, IC4 will recycle automatically.
            pass
