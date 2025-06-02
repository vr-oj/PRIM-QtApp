# File: prim_app/threads/sdk_camera_thread.py

import logging
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    # emitted when grabber is open & ready (so UI can build controls, if needed)
    grabber_ready = pyqtSignal()

    # emitted for each new frame: (QImage, raw_buffer_object)
    frame_ready = pyqtSignal(QImage, object)

    # emitted on error: (message, code)
    error = pyqtSignal(str, str)

    def __init__(self, parent=None, desired_fps=10):
        super().__init__(parent)
        self.grabber = None
        self._stop_requested = False
        # We will try to set AcquisitionFrameRate = desired_fps
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
                f"SDKCameraThread: selected device = {dev_info.model_name!r}, S/N={dev_info.serial!r}"
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

            # ─── 5) AUTOMATICALLY FIND THE “LARGEST” PIXELFORMAT/W×H ───────────────────
            # We iterate every entry in PixelFormat enumeration, set it, then read W&H,
            # and keep track of max(width*height).

            best_pf = None
            best_width = 0
            best_height = 0
            pf_node = self.grabber.device_property_map.find_enumeration("PixelFormat")
            if pf_node:
                for entry in pf_node.entries:
                    pf_name = entry.name
                    try:
                        # try setting that pixel format
                        pf_node.value = pf_name
                        w_node = self.grabber.device_property_map.find_integer("Width")
                        h_node = self.grabber.device_property_map.find_integer("Height")
                        if w_node and h_node:
                            w = int(w_node.value)
                            h = int(h_node.value)
                            # track largest area
                            if (w * h) > (best_width * best_height):
                                best_width = w
                                best_height = h
                                best_pf = pf_name
                    except Exception:
                        # skip any format that fails
                        continue

            if best_pf is None:
                raise RuntimeError(
                    "Could not find any PixelFormat/Width/Height combination."
                )

            # Now set the device to that “best” pixel format and resolution:
            log.info(
                f"SDKCameraThread: picked PF={best_pf!r} at W×H={best_width}×{best_height}"
            )
            pf_node.value = best_pf
            w_node = self.grabber.device_property_map.find_integer("Width")
            h_node = self.grabber.device_property_map.find_integer("Height")
            w_node.value = best_width
            h_node.value = best_height

            # ─── 6) TRY TO SET AcquisitionFrameRate = desired FPS (if that node exists) ──
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
                        f"SDKCameraThread: could not set AcquisitionFrameRate to {self._desired_fps}: {e}"
                    )

            # ─── 7) BUILD a QueueSink that hands you BGR8 buffers ───────────────────────
            listener = self  # we implement frames_queued() in this class
            sink = ic4.QueueSink(listener, [ic4.PixelFormat.BGR8], max_output_buffers=1)
            self.grabber.stream_setup(sink)

            # ─── 8) SIGNAL “grabber_ready” (UI could build dynamic controls if it cared) ─
            self.grabber_ready.emit()

            # ─── 9) START STREAMING ─────────────────────────────────────────────────────
            # As of IC4 v1.3.x, the method is grabber.stream_start(), not stream_begin()
            self.grabber.stream_start()
            log.info(
                "SDKCameraThread: stream_start() succeeded. Entering frame loop..."
            )

            # ─── 10) BUSY-LOOP, POPPING FRAMES until stop() is called ───────────────────
            while not self._stop_requested:
                ic4.sleep(
                    10
                )  # around 10 ms sleep (≈100 FPS spin-loop). No heavy CPU use.

            # ─── 11) STOP STREAMING & CLOSE DEVICE ─────────────────────────────────────
            self.grabber.stream_stop()
            self.grabber.device_close()
            log.info("SDKCameraThread: streaming stopped, device closed.")

        except Exception as e:
            log.exception("SDKCameraThread: encountered an error in run().")
            msg = str(e)
            code = getattr(e, "code", "")
            self.error.emit(msg, code)

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
            arr = buf.numpy_wrap()  # Numpy view: shape=(H, W, 3)
            h, w = arr.shape[0], arr.shape[1]

            # Build a QImage from the BGR data
            # Format_BGR888 is supported in recent PyQt5; adjust if your version needs Format_RGB888 + copy
            qimg = QImage(
                arr.data,
                w,
                h,
                arr.strides[0],
                QImage.Format_BGR888,
            )

            # Emit the frame to the UI
            self.frame_ready.emit(qimg, buf)

        except Exception as e:
            log.error(f"SDKCameraThread.frames_queued: Error popping buffer: {e}")
            self.error.emit(str(e), "")

        finally:
            # IC4 with max_output_buffers=1 will automatically recycle/queue the buffer again.
            pass
