# PRIM-QTAPP/prim_app/threads/sdk_camera_thread.py
import re
import numpy as np
import logging
import imagingcontrol4 as ic4 # Ensure ic4 is imported
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

log = logging.getLogger(__name__)

class MinimalSinkListener(ic4.QueueSinkListener):
    def __init__(self, owner_name="DefaultListener"):
        super().__init__()
        self.owner_name = owner_name
        log.debug(f"MinimalSinkListener '{self.owner_name}' created.")

    def frame_ready(self, sink: ic4.QueueSink, buffer: ic4.ImageBuffer, userdata: any): pass
    def frames_queued(self, sink: ic4.QueueSink): pass
    def sink_connected(self, sink: ic4.QueueSink, image_type_proposed: ic4.ImageType, userdata: any) -> bool:
        log.debug(f"Listener '{self.owner_name}': Sink connected. Proposed: {image_type_proposed}. Accepting.")
        return True
    def sink_disconnected(self, sink: ic4.QueueSink):
        log.debug(f"Listener '{self.owner_name}': Sink disconnected from {sink}.")
        pass
    def sink_property_changed(self, sink: ic4.QueueSink, property_name: str, userdata: any): pass


class SDKCameraThread(QThread):
    frame_ready = pyqtSignal(QImage, object)
    camera_error = pyqtSignal(str, str)

    def __init__(self, device_name=None, fps=10, parent=None):
        super().__init__(parent)
        self.device_identifier = device_name
        self.target_fps = float(fps) 
        self._stop_requested = False
        self.grabber = None; self.pm = None
        self.sink_listener = MinimalSinkListener(f"SDKThreadListener_{self.device_identifier or 'default'}")
        log.info(f"SDKCameraThread initialized for '{self.device_identifier}', target_fps (info): {self.target_fps}")

    def _attempt_set_property(self, prop_name: str, value_to_set: any, readable_value_for_log: str = None):
        if readable_value_for_log is None: readable_value_for_log = str(value_to_set)
        if not self.pm: log.error(f"PM not avail. Cannot set {prop_name}."); return
        prop_item = None
        try:
            prop_item = self.pm.find(prop_name)
            if prop_item:
                log.info(f"Attempting to set {prop_name} to {readable_value_for_log}...")
                self.pm.set_value(prop_name, value_to_set)
                rb_val = "(rb N/A)"; 
                try: rb_val = self.pm.get_value_str(prop_name)
                except Exception as e_rb: log.warning(f"Set {prop_name}, err reading back: {e_rb}")
                log.info(f"Set {prop_name}. Read back: {rb_val}")
            else: log.warning(f"{prop_name} not found.")
        except ic4.IC4Exception as e_p: log.error(f"IC4Exc setting {prop_name} to {readable_value_for_log}: {e_p} (Code: {e_p.code})")
        except AttributeError as ae: log.error(f"AttrErr for {prop_name} (item type: {type(prop_item)}): {ae}")
        except Exception as e_g: log.error(f"Generic exc setting {prop_name} to {readable_value_for_log}: {e_g}")

    def run(self):
        try:
            devices = ic4.DeviceEnum.devices()
            if not devices: raise RuntimeError("No IC4 devices found")
            target_dev = None
            if self.device_identifier:
                for dev in devices:
                    ds, du, dm = (dev.serial if hasattr(dev,"serial") else ""), (dev.unique_name if hasattr(dev,"unique_name") else ""), (dev.model_name if hasattr(dev,"model_name") else "")
                    if self.device_identifier in [ds,du,dm]: target_dev=dev; log.info(f"Found: {dm} SN:{ds} U:{du}"); break
                if not target_dev: raise RuntimeError(f"Cam '{self.device_identifier}' not found.")
            else: target_dev = devices[0]; log.info(f"Using first dev: {target_dev.model_name}")

            log.info(f"Opening: {target_dev.model_name}")
            self.grabber = ic4.Grabber(); self.grabber.device_open(target_dev)
            self.pm = self.grabber.device_property_map; log.info(f"Device {target_dev.model_name} opened. PM acquired.")

            log.info("Configuring essential properties...")
            self._attempt_set_property("PixelFormat", ic4.PixelFormat.Mono8, "Mono8")
            self._attempt_set_property("Width", 640, "640") # Try lower resolution
            self._attempt_set_property("Height", 480, "480")
            self._attempt_set_property("AcquisitionMode", "Continuous", "Continuous")
            self._attempt_set_property("TriggerMode", "Off", "Off")
            log.info("Finished essential property config attempt.")

            self.sink = ic4.QueueSink(listener=self.sink_listener); log.info("QueueSink initialized.")
            
            # USER SUGGESTED SEQUENCE: Prepare first, then explicitly start
            log.debug("Calling stream_setup with PREPARE_ACQUISITION_AND_QUEUE_BUFFERS...")
            self.grabber.stream_setup(self.sink, setup_option=ic4.StreamSetupOption.PREPARE_ACQUISITION_AND_QUEUE_BUFFERS)
            log.info("stream_setup (PREPARE_ACQUISITION_AND_QUEUE_BUFFERS) completed.")

            if self.grabber.is_acquisition_active:
                log.warning("Acquisition became active from PREPARE_ACQUISITION option. This is unexpected but proceeding.")
            else:
                log.info("Acquisition not active after PREPARE. Attempting explicit acquisition_start()...")
                self.grabber.acquisition_start()
                if not self.grabber.is_acquisition_active:
                    log.error("Explicit acquisition_start() FAILED after prepare.")
                    raise RuntimeError("Camera acquisition failed: explicit start post-prepare did not activate.")
                else:
                    log.info("Explicit acquisition_start() SUCCEEDED.")
            
            # Final confirmation
            if not self.grabber.is_acquisition_active:
                log.critical("Acquisition STILL NOT active before loop. Aborting.")
                raise RuntimeError("Camera acquisition could not be confirmed.")
            
            log.info("Stream active. Pausing briefly..."); QThread.msleep(250); log.info("Pause complete. Entering frame loop...")
            
            while not self._stop_requested:
                buf = None 
                try:
                    buf = self.sink.pop_output_buffer() 
                    if buf: 
                        # log.debug(f"Popped buffer: {type(buf)}") # Reduce log spam once working
                        arr = buf.numpy_wrap()
                        q_image_format = QImage.Format_Grayscale8 
                        if arr.ndim == 3 and arr.shape[2] == 3: q_image_format = QImage.Format_BGR888 
                        elif arr.ndim == 2 or (arr.ndim == 3 and arr.shape[2] == 1): q_image_format = QImage.Format_Grayscale8
                        else: log.warning(f"Unsupported arr shape: {arr.shape}. Skip."); buf.release(); continue
                        final_arr = arr[..., 0] if (arr.ndim == 3 and q_image_format == QImage.Format_Grayscale8 and arr.shape[2] == 1) else arr
                        q_image = QImage(final_arr.data, final_arr.shape[1], final_arr.shape[0], final_arr.strides[0], q_image_format)
                        self.frame_ready.emit(q_image.copy(), arr.copy())
                        buf.release() 
                    else: 
                        if self._stop_requested: log.debug("Stop req, buf None, exit loop."); break
                        QThread.msleep(10); continue
                except ic4.IC4Exception as e:
                    if e.code in [ic4.ErrorCode.Timeout, ic4.ErrorCode.NoData]:
                        if self._stop_requested: break
                        QThread.msleep(5 if e.code == ic4.ErrorCode.NoData else 1); continue
                    else: log.error(f"Unhandled IC4Exc in loop: {e} (Code:{e.code}), breaking."); self.camera_error.emit(str(e), str(e.code)); break 
                except AttributeError as ae: 
                    log.error(f"AttrErr in loop: {ae}"); self.camera_error.emit(str(ae), "ATTR_ERR_BUF")
                    if buf and hasattr(buf, 'release'): try: buf.release() except Exception as e_rls: log.error(f"Err releasing buf: {e_rls}")
                    break 
                except Exception as e_loop: 
                    log.exception(f"Generic exc in loop: {e_loop}"); self.camera_error.emit(str(e_loop), "LOOP_ERR")
                    if buf and hasattr(buf, 'release'): try: buf.release() except Exception as e_rls: log.error(f"Err releasing buf: {e_rls}")
                    break 
            log.info("Exited acquisition loop.")
        except RuntimeError as e_rt: log.error(f"RuntimeError in run: {e_rt}"); self.camera_error.emit(str(e_rt), "RUNTIME_SETUP_ERROR")
        except ic4.IC4Exception as e_setup: log.error(f"IC4Exc in setup: {e_setup} (Code:{e_setup.code})"); self.camera_error.emit(str(e_setup), str(e_setup.code))
        except Exception as ex_outer: log.exception(f"Outer unhandled exc: {ex_outer}"); self.camera_error.emit(str(ex_outer), type(ex_outer).__name__)
        finally:
            log.debug("Run method finally block.");
            if self.grabber:
                try:
                    if self.grabber.is_acquisition_active: log.debug("Stopping acq (finally)..."); self.grabber.acquisition_stop()
                except Exception as e: log.error(f"Finally: Err stopping acq: {e}")
                try:
                    if self.grabber.is_device_open: log.debug("Closing dev (finally)..."); self.grabber.device_close()
                except Exception as e: log.error(f"Finally: Err closing dev: {e}")
            self.grabber = None; self.pm = None
            log.info("Run method finished cleanup.")

    def stop(self):
        log.info(f"Stop() for {self.device_identifier}."); self._stop_requested = True 
        if self.isRunning():
            log.debug(f"Waiting for {self.device_identifier} to finish...");
            if not self.wait(3000): log.warning(f"{self.device_identifier} unresponsive, terminating."); self.terminate(); self.wait(500) 
            else: log.info(f"{self.device_identifier} finished gracefully.")
        else: log.info(f"{self.device_identifier} not running when stop called.")
        log.info(f"Stop() completed for {self.device_identifier}.")