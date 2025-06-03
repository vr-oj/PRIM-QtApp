# File: prim_app/threads/sdk_camera_thread.py

import logging
import imagingcontrol4 as ic4
from PyQt5.QtCore import QThread, pyqtSignal

log = logging.getLogger(__name__)


class SDKCameraThread(QThread):
    # Emitted once the camera is opened and basic nodes are set.
    grabber_ready = pyqtSignal()

    # Emitted on any error. The second argument here is a string, not an ErrorCode.
    error = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grabber = None
        self._stop_requested = False

    def run(self):
        try:
            # ─── 1) Initialize IC4 exactly once ────────────────────────────────────
            ic4.Library.init(
                api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR
            )
            log.info("SDKCameraThread: Library.init() succeeded.")

            # ─── 2) Enumerate & Open the first camera ─────────────────────────────
            devices = ic4.DeviceEnum.devices()
            if not devices:
                raise RuntimeError("No IC4 camera devices found.")
            dev_info = devices[0]
            log.info(
                f"SDKCameraThread: Opening camera {dev_info.model_name!r} (S/N {dev_info.serial!r})"
            )

            self.grabber = ic4.Grabber()
            self.grabber.device_open(dev_info)
            log.info("SDKCameraThread: device_open() succeeded.")

            # ─── 3) Apply the same acquisition settings as grab_one_frame.py ────────
            # 3a) Try Mono8 if available
            try:
                pf_node = self.grabber.device_property_map.find_enumeration(
                    ic4.PropId.PIXEL_FORMAT
                )
                if pf_node:
                    mono8_options = [
                        e.name
                        for e in pf_node.entries
                        if e.is_available and "Mono8" in e.name
                    ]
                    if mono8_options:
                        pf_node.value = "Mono8"
                        log.info("  → PIXEL_FORMAT set to Mono8")
                    else:
                        log.warning(
                            "  → No Mono8 entry available; leaving default PF unchanged."
                        )
                else:
                    log.warning("  → PIXEL_FORMAT node not found.")
            except Exception as e:
                log.warning(f"  ✗ Cannot set PIXEL_FORMAT: {e}")

            # 3b) AcquisitionMode → Continuous
            try:
                acq_node = self.grabber.device_property_map.find_enumeration(
                    ic4.PropId.ACQUISITION_MODE
                )
                if acq_node:
                    modes = [e.name for e in acq_node.entries if e.is_available]
                    if "Continuous" in modes:
                        acq_node.value = "Continuous"
                        log.info("  → ACQUISITION_MODE set to Continuous")
                    else:
                        log.warning(
                            f"  → 'Continuous' not available (options: {modes}); leaving default."
                        )
                else:
                    log.warning("  → ACQUISITION_MODE node not found.")
            except Exception as e:
                log.warning(f"  ✗ Cannot set ACQUISITION_MODE: {e}")

            # 3c) AcquisitionFrameRate → 10.0
            try:
                fr_node = self.grabber.device_property_map.find_float(
                    ic4.PropId.ACQUISITION_FRAME_RATE
                )
                if fr_node:
                    fr_node.value = 10.0
                    log.info("  → ACQUISITION_FRAME_RATE set to 10.0 FPS")
                else:
                    log.warning("  → ACQUISITION_FRAME_RATE node not found.")
            except Exception as e:
                log.warning(f"  ✗ Cannot set ACQUISITION_FRAME_RATE: {e}")

            # 3d) ExposureTime → 30000 µs (30 ms)
            try:
                exp_node = self.grabber.device_property_map.find_float(
                    ic4.PropId.EXPOSURE_TIME
                )
                if exp_node:
                    exp_node.value = 30000.0
                    log.info("  → EXPOSURE_TIME set to 30 ms")
                else:
                    log.warning("  → EXPOSURE_TIME node not found.")
            except Exception as e:
                log.warning(f"  ✗ Cannot set EXPOSURE_TIME: {e}")

            # 3e) Gain → 10.0
            try:
                gain_node = self.grabber.device_property_map.find_float(ic4.PropId.GAIN)
                if gain_node:
                    gain_node.value = 10.0
                    log.info("  → GAIN set to 10.0")
                else:
                    log.warning("  → GAIN node not found.")
            except Exception as e:
                log.warning(f"  ✗ Cannot set GAIN: {e}")

            # ─── 4) Emit grabber_ready so the UI knows it can query self.grabber now ───
            self.grabber_ready.emit()

            # ─── 5) Wait here until someone calls stop() ─────────────────────────────
            while not self._stop_requested:
                self.msleep(100)  # sleep 100 ms at a time, low CPU usage

            # ─── 6) Clean up & close device ────────────────────────────────────────
            try:
                self.grabber.device_close()
                log.info("SDKCameraThread: device_close() succeeded.")
            except Exception:
                pass

        except Exception as e:
            # If anything fails, convert e.code (if present) to a string
            msg = str(e)
            code_enum = getattr(e, "code", None)
            code_str = str(code_enum) if code_enum else ""
            log.exception("SDKCameraThread: encountered an error.")
            self.error.emit(msg, code_str)

        finally:
            # Always call Library.exit() exactly once per thread
            try:
                ic4.Library.exit()
                log.info("SDKCameraThread: Library.exit() called.")
            except Exception:
                pass

    def stop(self):
        self._stop_requested = True
