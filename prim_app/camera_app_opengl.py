# File: camera_app_opengl.py

import sys
import time

# IC4 SDK for camera control
import imagingcontrol4 as ic4

# PyQt5 for GUI and OpenGL
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QCheckBox,
    QSlider,
    QGroupBox,
    QMessageBox,
    QOpenGLWidget,  # <— QOpenGLWidget lives in QtWidgets
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPainter

# NumPy for array handling (used by ImageBuffer.numpy_wrap())
import numpy as np


class IC4CameraController:
    """
    Wraps IC4 Grabber + QueueSink to detect, open, and control DMK cameras.

    Steps on open():
      1. ic4.Library.init()
      2. Enumerate devices via DeviceEnum.devices() and pick DMK 33UX250 / 33UP5000  [oai_citation:8‡The Imaging Source](https://www.theimagingsource.com/en-us/documentation/ic4python/api-reference.html?utm_source=chatgpt.com).
      3. Open with Grabber.device_open().
      4. Set AcquisitionMode="Continuous", AcquisitionFrameRate=10.0  [oai_citation:9‡The Imaging Source](https://www.theimagingsource.com/en-us/documentation/ic4python/api-reference.html?utm_source=chatgpt.com) [oai_citation:10‡The Imaging Source](https://www.theimagingsource.com/en-us/documentation/ic4python/api-reference.html?utm_source=chatgpt.com).
      5. Create QueueSink, stream_setup(sink, StreamSetupOption.ACQUISITION_START), alloc_and_queue_buffers().
    """

    def __init__(self, preferred_models=None):
        # By default, look for these substrings in each DeviceInfo.model_name:
        self.preferred_models = preferred_models or ["DMK 33UX250", "DMK 33UP5000"]
        self.grabber = None
        self.sink = None

    def list_devices(self):
        """
        Returns a list of DeviceInfo objects for all video capture devices.
        Use DeviceInfo.model_name, serial, etc.
        """
        return (
            ic4.DeviceEnum.devices()
        )  #  [oai_citation:11‡The Imaging Source](https://www.theimagingsource.com/en-us/documentation/ic4python/api-reference.html?utm_source=chatgpt.com)

    def open(self):
        """
        1. Initialize the library (once per process).
        2. Pick first matching model or fallback to the first device.
        3. Open it via Grabber().
        4. Configure AcquisitionMode + frame rate.
        5. Attach a QueueSink and start streaming at 10 FPS.
        Returns True on success, False otherwise.
        """
        try:
            ic4.Library.init()  # Initialize the IC4 library  [oai_citation:12‡The Imaging Source](https://www.theimagingsource.com/en-us/documentation/ic4python/api-reference.html?utm_source=chatgpt.com)
        except ic4.IC4Exception as e:
            QMessageBox.critical(None, "IC4 Error", f"Library.init() failed:\n{e}")
            return False

        # Enumerate all DeviceInfo objects
        try:
            devices = (
                ic4.DeviceEnum.devices()
            )  #  [oai_citation:13‡The Imaging Source](https://www.theimagingsource.com/en-us/documentation/ic4python/api-reference.html?utm_source=chatgpt.com)
        except ic4.IC4Exception as e:
            QMessageBox.critical(
                None, "IC4 Error", f"Failed to enumerate devices:\n{e}"
            )
            return False

        if len(devices) == 0:
            QMessageBox.critical(None, "Camera Error", "No IC4 devices found.")
            return False

        # Pick first matching preferred_model, else fallback to devices[0]
        chosen_info = None
        for info in devices:
            name = info.model_name  # e.g. "DMK 33UX250"
            for pref in self.preferred_models:
                if pref in name:
                    chosen_info = info
                    break
            if chosen_info:
                break
        if chosen_info is None:
            chosen_info = devices[0]

        # Create Grabber, open device
        try:
            self.grabber = ic4.Grabber()
            self.grabber.device_open(chosen_info)
        except ic4.IC4Exception as e:
            QMessageBox.critical(None, "IC4 Error", f"Failed to open device:\n{e}")
            return False

        # Configure AcquisitionMode = "Continuous", and set frame rate to 10.0
        pm = self.grabber.device_property_map
        try:
            # NOTE: PropId.ACQUISITION_MODE is an enumeration; "Continuous" ensures ongoing streaming
            pm.set_value(ic4.PropId.ACQUISITION_MODE, "Continuous")
            pm.set_value(ic4.PropId.ACQUISITION_FRAME_RATE, 10.0)
        except ic4.IC4Exception as e:
            QMessageBox.warning(
                None,
                "Warning",
                f"Could not set Acquisition Mode/Rate:\n{e}\nProceeding with defaults.",
            )

        # Create a QueueSink, attach it, and immediately start acquisition
        try:
            self.sink = ic4.QueueSink()
            self.grabber.stream_setup(
                self.sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )  #  [oai_citation:14‡The Imaging Source](https://www.theimagingsource.com/en-us/documentation/ic4python/api-reference.html?utm_source=chatgpt.com)
            # Pre‐allocate, say, 10 buffers. The default allocation strategy will size them
            self.sink.alloc_and_queue_buffers(10)
        except ic4.IC4Exception as e:
            QMessageBox.critical(
                None, "IC4 Error", f"Failed to create or attach QueueSink:\n{e}"
            )
            self.grabber = None
            return False

        return True

    def close(self):
        """Stop streaming, delete Grabber & Sink."""
        if self.grabber:
            try:
                # Stop acquisition first (optional: explicit)
                self.grabber.acquisition_stop()
            except:
                pass
            try:
                self.grabber.device_close()
            except:
                pass
        self.grabber = None
        self.sink = None

    def __del__(self):
        self.close()

    # ———————————————————————————————
    # PROPERTY‐QUERY / PROPERTY‐SET HELPERS
    # ———————————————————————————————

    def _get_integer_property(self, prop_id):
        """
        Return the PropInteger object for the given prop_id name (string).
        E.g. ic4.PropId.EXPOSURE, ic4.PropId.GAIN, etc.
        """
        pm = self.grabber.device_property_map
        try:
            return pm.find_integer(prop_id)
        except ic4.IC4Exception:
            return None

    def _get_boolean_property(self, prop_id):
        """Return the PropBoolean object for the given prop_id (string)."""
        pm = self.grabber.device_property_map
        try:
            return pm.find_boolean(prop_id)
        except ic4.IC4Exception:
            return None

    def _get_auto_property(self, auto_id):
        """
        Many “Auto X” features are enumeration or boolean features:
         - For auto exposure, PropId.EXPOSURE_AUTO might exist
         - For auto white balance, PropId.WHITE_BALANCE_AUTO, etc.
        We attempt to find them as boolean first, else as enumeration.
        """
        # Try boolean
        b = self._get_boolean_property(auto_id)
        if b:
            return b
        # If not boolean, try enumeration
        pm = self.grabber.device_property_map
        try:
            return pm.find_enumeration(auto_id)
        except ic4.IC4Exception:
            return None

    def get_auto_exposure(self) -> bool:
        """
        Return True if Auto Exposure is ON (if the camera supports it).
        """
        prop = self._get_auto_property(ic4.PropId.EXPOSURE_AUTO)
        if not prop:
            return False
        try:
            return bool(prop.value)
        except:
            return False

    def set_auto_exposure(self, enabled: bool):
        """
        Toggle Auto Exposure ON / OFF. If OFF, one can set Exposure manually.
        """
        prop = self._get_auto_property(ic4.PropId.EXPOSURE_AUTO)
        if not prop:
            return
        try:
            prop.value = bool(enabled)
        except ic4.IC4Exception as e:
            print(f"[IC4] Failed to set AutoExposure: {e}")

    def get_exposure_range(self):
        """
        Return (valid_values_list) for Exposure. We will use valid_value_set,
        which returns a list of allowed integer exposure values.
        """
        prop = self._get_integer_property(ic4.PropId.EXPOSURE)
        if not prop:
            return []
        try:
            return list(prop.valid_value_set)
        except:
            return []

    def get_current_exposure(self) -> int:
        """Return current Exposure (as int) or 0 if unavailable."""
        prop = self._get_integer_property(ic4.PropId.EXPOSURE)
        if not prop:
            return 0
        try:
            return int(prop.value)
        except:
            return 0

    def set_exposure(self, value: int):
        """
        Turn off AutoExposure, then set Exposure to value (one of valid_value_set).
        """
        self.set_auto_exposure(False)
        prop = self._get_integer_property(ic4.PropId.EXPOSURE)
        if not prop:
            return
        try:
            prop.value = int(value)
        except ic4.IC4Exception as e:
            print(f"[IC4] Failed to set Exposure: {e}")

    def get_gain_range(self):
        """
        Return list of allowed Gain values (PropInteger.valid_value_set).
        """
        prop = self._get_integer_property(
            ic4.PropId.GAIN_RAW
        ) or self._get_integer_property(ic4.PropId.GAIN)
        if not prop:
            return []
        try:
            return list(prop.valid_value_set)
        except:
            return []

    def get_current_gain(self) -> int:
        """Return current Gain (or 0)."""
        prop = self._get_integer_property(
            ic4.PropId.GAIN_RAW
        ) or self._get_integer_property(ic4.PropId.GAIN)
        if not prop:
            return 0
        try:
            return int(prop.value)
        except:
            return 0

    def set_gain(self, value: int):
        """
        Set Gain to value (PropId.GAIN or PropId.GAIN_RAW).
        """
        prop = self._get_integer_property(
            ic4.PropId.GAIN_RAW
        ) or self._get_integer_property(ic4.PropId.GAIN)
        if not prop:
            return
        try:
            prop.value = int(value)
        except ic4.IC4Exception as e:
            print(f"[IC4] Failed to set Gain: {e}")

    def get_brightness_range(self):
        """
        Return list of allowed Brightness values (PropInteger.valid_value_set).
        """
        prop = self._get_integer_property(ic4.PropId.BRIGHTNESS)
        if not prop:
            return []
        try:
            return list(prop.valid_value_set)
        except:
            return []

    def get_current_brightness(self) -> int:
        """Return current Brightness (or 0)."""
        prop = self._get_integer_property(ic4.PropId.BRIGHTNESS)
        if not prop:
            return 0
        try:
            return int(prop.value)
        except:
            return 0

    def set_brightness(self, value: int):
        """Set Brightness to value (PropId.BRIGHTNESS)."""
        prop = self._get_integer_property(ic4.PropId.BRIGHTNESS)
        if not prop:
            return
        try:
            prop.value = int(value)
        except ic4.IC4Exception as e:
            print(f"[IC4] Failed to set Brightness: {e}")

    def get_auto_white_balance(self) -> bool:
        """Return True if Auto White Balance is ON."""
        prop = self._get_auto_property(ic4.PropId.WHITE_BALANCE_AUTO)
        if not prop:
            return False
        try:
            return bool(prop.value)
        except:
            return False

    def set_auto_white_balance(self, enabled: bool):
        """Toggle Auto White Balance ON / OFF."""
        prop = self._get_auto_property(ic4.PropId.WHITE_BALANCE_AUTO)
        if not prop:
            return
        try:
            prop.value = bool(enabled)
        except ic4.IC4Exception as e:
            print(f"[IC4] Failed to set WhiteBalanceAuto: {e}")

    def get_white_balance_range(self):
        """
        Return two lists: valid Red values and valid Blue values for manual WB.
        Those come from PropInteger.valid_value_set for PropId.WHITE_BALANCE_RED and PropId.WHITE_BALANCE_BLUE.
        """
        red_prop = self._get_integer_property(ic4.PropId.WHITE_BALANCE_RED)
        blue_prop = self._get_integer_property(ic4.PropId.WHITE_BALANCE_BLUE)
        reds = list(red_prop.valid_value_set) if red_prop else []
        blues = list(blue_prop.valid_value_set) if blue_prop else []
        return reds, blues

    def get_current_white_balance(self):
        """Return (current_red, current_blue), or (0, 0)."""
        red_val, blue_val = 0, 0
        red_prop = self._get_integer_property(ic4.PropId.WHITE_BALANCE_RED)
        blue_prop = self._get_integer_property(ic4.PropId.WHITE_BALANCE_BLUE)
        if red_prop:
            try:
                red_val = int(red_prop.value)
            except:
                pass
        if blue_prop:
            try:
                blue_val = int(blue_prop.value)
            except:
                pass
        return red_val, blue_val

    def set_white_balance(self, red: int, blue: int):
        """
        Turn off Auto White Balance, then set WHITE_BALANCE_RED and WHITE_BALANCE_BLUE.
        """
        self.set_auto_white_balance(False)
        red_prop = self._get_integer_property(ic4.PropId.WHITE_BALANCE_RED)
        blue_prop = self._get_integer_property(ic4.PropId.WHITE_BALANCE_BLUE)
        try:
            if red_prop:
                red_prop.value = int(red)
            if blue_prop:
                blue_prop.value = int(blue)
        except ic4.IC4Exception as e:
            print(f"[IC4] Failed to set WhiteBalance(R,B): {e}")


class IC4CameraThread(QThread):
    """
    QThread that continuously pops the newest ImageBuffer from a QueueSink
    and emits it as a NumPy array (dtype=uint8, or uint16 depending on pixel format).
    """

    frame_ready = pyqtSignal(object)  # will emit a NumPy ndarray

    def __init__(self, sink: ic4.QueueSink, parent=None):
        super().__init__(parent)
        self.sink = sink
        self._running = False

    def run(self):
        self._running = True
        while self._running:
            try:
                buf = (
                    self.sink.try_pop_output_buffer()
                )  #  [oai_citation:15‡The Imaging Source](https://www.theimagingsource.com/en-us/documentation/ic4python/api-reference.html?utm_source=chatgpt.com)
            except ic4.IC4Exception as e:
                print(f"[IC4Thread] Error popping buffer: {e}")
                buf = None

            if buf is None:
                # No frame available right now; just loop
                time.sleep(0.001)
                continue

            # Convert ImageBuffer → NumPy (shares memory)
            try:
                arr = (
                    buf.numpy_wrap()
                )  #  [oai_citation:16‡The Imaging Source](https://www.theimagingsource.com/en-us/documentation/ic4python/api-reference.html?utm_source=chatgpt.com)
                # arr is an (H,W,channels) array of dtype c_ubyte or c_ushort
                # Convert to a contiguous uint8/uint16 array in case downstream code expects it
                np_img = np.array(arr, copy=False)
                # Emit that frame
                self.frame_ready.emit(np_img)
            except Exception as e:
                print(f"[IC4Thread] Failed to numpy_wrap(): {e}")
            finally:
                # Always release the buffer so it can be reused
                try:
                    buf.release()
                except:
                    pass

        # End of run, nothing else to do

    def stop(self):
        """Request thread to stop, then wait() for it to finish."""
        self._running = False
        self.wait()


class CameraOpenGLWidget(QOpenGLWidget):
    """
    A QOpenGLWidget that draws incoming NumPy frames (uint8/uint16) with QPainter.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.current_image = None  # QImage

    def update_frame(self, np_img):
        """
        Convert a NumPy array (H×W×C) to QImage and schedule repaint.
        We assume np_img.dtype is uint8 or uint16, and channels=1 or 3 or 4.
        For simplicity, we convert to 8‐bit RGB for display.
        """
        if np_img is None:
            return

        h, w, c = np_img.shape

        # If it’s 10/12/16‐bit grayscale or Bayer/Mono16, we scale down to 8‐bit
        if np_img.dtype == np.uint16 and c == 1:
            # Normalize 16→8
            arr8 = (np_img >> 8).astype(np.uint8)
            # Create QImage Format_Grayscale8 (1 channel)
            image = QImage(arr8.data, w, h, w, QImage.Format_Grayscale8)
        elif np_img.dtype == np.uint8 and c == 1:
            # Single‐channel 8‐bit → QImage.Format_Grayscale8
            image = QImage(np_img.data, w, h, w, QImage.Format_Grayscale8)
        elif np_img.dtype == np.uint8 and c == 3:
            # BGR8 → RGB888 explicitly
            rgb = np_img[..., ::-1]
            bytes_per_line = 3 * w
            image = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        elif np_img.dtype == np.uint8 and c == 4:
            # BGRA8 → RGBA8888
            rgba = np_img[..., [2, 1, 0, 3]]
            bytes_per_line = 4 * w
            image = QImage(rgba.data, w, h, bytes_per_line, QImage.Format_RGBA8888)
        else:
            # Other formats not explicitly handled—attempt generic 8‐bit copy to RGB
            np8 = np_img.astype(np.uint8)
            if c == 2:
                # hypothetical case: 2 channel, drop alpha
                rgb = np.dstack((np8[:, :, 0], np8[:, :, 0], np8[:, :, 0]))
                bytes_per_line = 3 * w
                image = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
            else:
                # Last resort: flatten into grayscale8
                gray = cv2.cvtColor(np8, cv2.COLOR_BGR2GRAY)
                image = QImage(gray.data, w, h, w, QImage.Format_Grayscale8)

        # Scale image to fit widget, keeping aspect ratio
        self.current_image = image.scaled(
            self.width(), self.height(), Qt.KeepAspectRatio
        )
        self.update()

    def paintGL(self):
        """
        Called whenever Qt decides the widget needs repainting. We draw the QImage centered.
        """
        self.makeCurrent()
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.black)
        if self.current_image:
            x = (self.width() - self.current_image.width()) // 2
            y = (self.height() - self.current_image.height()) // 2
            painter.drawImage(x, y, self.current_image)
        painter.end()

    def resizeGL(self, w, h):
        """
        When the widget resizes, re‐scale the last image to fit the new size.
        """
        if self.current_image:
            self.current_image = self.current_image.scaled(w, h, Qt.KeepAspectRatio)


class CameraAppMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Standalone IC4 Camera App (OpenGL)")
        self.setGeometry(200, 200, 1024, 600)

        self.ic4_ctrl = None
        self.ic4_thread = None

        # Build the UI
        self._build_ui()

    def _build_ui(self):
        # Central widget & layout
        central = QWidget()
        main_layout = QHBoxLayout()
        central.setLayout(main_layout)
        self.setCentralWidget(central)

        # Left: OpenGL preview
        self.opengl_widget = CameraOpenGLWidget()
        main_layout.addWidget(self.opengl_widget)

        # Right: Controls
        controls_container = QWidget()
        controls_layout = QVBoxLayout()
        controls_container.setLayout(controls_layout)
        main_layout.addWidget(controls_container)

        # — Connection Buttons —
        self.connect_btn = QPushButton("Connect Camera")
        self.connect_btn.clicked.connect(self.on_connect)
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self.on_disconnect)
        self.disconnect_btn.setEnabled(False)

        controls_layout.addWidget(self.connect_btn)
        controls_layout.addWidget(self.disconnect_btn)

        # — Exposure Control Group —
        ae_group = QGroupBox("Exposure Control")
        ae_layout = QVBoxLayout()
        ae_group.setLayout(ae_layout)
        controls_layout.addWidget(ae_group)

        # Auto Exposure checkbox
        self.ae_checkbox = QCheckBox("Auto Exposure")
        self.ae_checkbox.setChecked(True)
        self.ae_checkbox.setEnabled(False)
        self.ae_checkbox.stateChanged.connect(self.on_toggle_ae)
        ae_layout.addWidget(self.ae_checkbox)

        # Manual Exposure slider
        self.exposure_label = QLabel("Exposure: N/A")
        self.exposure_slider = QSlider(Qt.Horizontal)
        self.exposure_slider.setEnabled(False)
        self.exposure_slider.valueChanged.connect(self.on_exposure_change)
        ae_layout.addWidget(self.exposure_label)
        ae_layout.addWidget(self.exposure_slider)

        # Gain slider
        self.gain_label = QLabel("Gain: N/A")
        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setEnabled(False)
        self.gain_slider.valueChanged.connect(self.on_gain_change)
        ae_layout.addWidget(self.gain_label)
        ae_layout.addWidget(self.gain_slider)

        # Brightness slider
        self.brightness_label = QLabel("Brightness: N/A")
        self.brightness_slider = QSlider(Qt.Horizontal)
        self.brightness_slider.setEnabled(False)
        self.brightness_slider.valueChanged.connect(self.on_brightness_change)
        ae_layout.addWidget(self.brightness_label)
        ae_layout.addWidget(self.brightness_slider)

        # — White Balance Group —
        wb_group = QGroupBox("White Balance")
        wb_layout = QVBoxLayout()
        wb_group.setLayout(wb_layout)
        controls_layout.addWidget(wb_group)

        # Auto White Balance checkbox
        self.wb_auto_checkbox = QCheckBox("Auto White Balance")
        self.wb_auto_checkbox.setChecked(True)
        self.wb_auto_checkbox.setEnabled(False)
        self.wb_auto_checkbox.stateChanged.connect(self.on_toggle_wb_auto)
        wb_layout.addWidget(self.wb_auto_checkbox)

        # Manual WB Red slider
        self.wb_red_label = QLabel("WB Red: N/A")
        self.wb_red_slider = QSlider(Qt.Horizontal)
        self.wb_red_slider.setEnabled(False)
        self.wb_red_slider.valueChanged.connect(self.on_wb_red_change)
        wb_layout.addWidget(self.wb_red_label)
        wb_layout.addWidget(self.wb_red_slider)

        # Manual WB Blue slider
        self.wb_blue_label = QLabel("WB Blue: N/A")
        self.wb_blue_slider = QSlider(Qt.Horizontal)
        self.wb_blue_slider.setEnabled(False)
        self.wb_blue_slider.valueChanged.connect(self.on_wb_blue_change)
        wb_layout.addWidget(self.wb_blue_label)
        wb_layout.addWidget(self.wb_blue_slider)

        # Spacer to push controls upward
        controls_layout.addStretch()

    def on_connect(self):
        """
        Called when “Connect Camera” is clicked.
        1. Instantiate IC4CameraController, open the camera.
        2. If success: enable controls, populate sliders from each property’s valid_value_set.
        3. Start IC4CameraThread to feed frames to the OpenGL widget.
        """
        self.ic4_ctrl = IC4CameraController(
            preferred_models=["DMK 33UX250", "DMK 33UP5000"]
        )
        success = self.ic4_ctrl.open()
        if not success:
            self.ic4_ctrl = None
            return

        # Disable Connect, enable Disconnect
        self.connect_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(True)

        # Enable/disable checkboxes
        self.ae_checkbox.setEnabled(True)
        self.wb_auto_checkbox.setEnabled(True)

        # Set initial AE / WB checkbox states
        self.ae_checkbox.setChecked(self.ic4_ctrl.get_auto_exposure())
        self.wb_auto_checkbox.setChecked(self.ic4_ctrl.get_auto_white_balance())

        # Populate Exposure slider
        exp_vals = self.ic4_ctrl.get_exposure_range()
        if exp_vals:
            e_min, e_max = exp_vals[0], exp_vals[-1]
            e_step = exp_vals[1] - exp_vals[0] if len(exp_vals) > 1 else 1
            self.exposure_slider.setMinimum(e_min)
            self.exposure_slider.setMaximum(e_max)
            self.exposure_slider.setSingleStep(e_step)
            curr_e = self.ic4_ctrl.get_current_exposure()
            self.exposure_slider.setValue(curr_e)
            self.exposure_label.setText(f"Exposure: {curr_e}")
            # Initially disable if auto exposure is ON
            self.exposure_slider.setEnabled(not self.ic4_ctrl.get_auto_exposure())
        else:
            self.exposure_label.setText("Exposure: N/A")
            self.exposure_slider.setEnabled(False)

        # Populate Gain slider
        gain_vals = self.ic4_ctrl.get_gain_range()
        if gain_vals:
            g_min, g_max = gain_vals[0], gain_vals[-1]
            g_step = gain_vals[1] - gain_vals[0] if len(gain_vals) > 1 else 1
            self.gain_slider.setMinimum(g_min)
            self.gain_slider.setMaximum(g_max)
            self.gain_slider.setSingleStep(g_step)
            curr_g = self.ic4_ctrl.get_current_gain()
            self.gain_slider.setValue(curr_g)
            self.gain_label.setText(f"Gain: {curr_g}")
            self.gain_slider.setEnabled(not self.ic4_ctrl.get_auto_exposure())
        else:
            self.gain_label.setText("Gain: N/A")
            self.gain_slider.setEnabled(False)

        # Populate Brightness slider
        br_vals = self.ic4_ctrl.get_brightness_range()
        if br_vals:
            b_min, b_max = br_vals[0], br_vals[-1]
            b_step = br_vals[1] - br_vals[0] if len(br_vals) > 1 else 1
            self.brightness_slider.setMinimum(b_min)
            self.brightness_slider.setMaximum(b_max)
            self.brightness_slider.setSingleStep(b_step)
            curr_b = self.ic4_ctrl.get_current_brightness()
            self.brightness_slider.setValue(curr_b)
            self.brightness_label.setText(f"Brightness: {curr_b}")
            self.brightness_slider.setEnabled(not self.ic4_ctrl.get_auto_exposure())
        else:
            self.brightness_label.setText("Brightness: N/A")
            self.brightness_slider.setEnabled(False)

        # Populate White Balance sliders
        (r_vals, bl_vals) = self.ic4_ctrl.get_white_balance_range()
        if r_vals and bl_vals:
            r_min, r_max = r_vals[0], r_vals[-1]
            r_step = r_vals[1] - r_vals[0] if len(r_vals) > 1 else 1
            self.wb_red_slider.setMinimum(r_min)
            self.wb_red_slider.setMaximum(r_max)
            self.wb_red_slider.setSingleStep(r_step)
            curr_r, curr_b = self.ic4_ctrl.get_current_white_balance()
            self.wb_red_slider.setValue(curr_r)
            self.wb_red_label.setText(f"WB Red: {curr_r}")

            b_min, b_max = bl_vals[0], bl_vals[-1]
            b_step = bl_vals[1] - bl_vals[0] if len(bl_vals) > 1 else 1
            self.wb_blue_slider.setMinimum(b_min)
            self.wb_blue_slider.setMaximum(b_max)
            self.wb_blue_slider.setSingleStep(b_step)
            self.wb_blue_slider.setValue(curr_b)
            self.wb_blue_label.setText(f"WB Blue: {curr_b}")

            # Disable both if auto WB is ON
            enabled_manual_wb = not self.ic4_ctrl.get_auto_white_balance()
            self.wb_red_slider.setEnabled(enabled_manual_wb)
            self.wb_blue_slider.setEnabled(enabled_manual_wb)
        else:
            self.wb_auto_checkbox.setEnabled(False)
            self.wb_red_label.setText("WB Red: N/A")
            self.wb_red_slider.setEnabled(False)
            self.wb_blue_label.setText("WB Blue: N/A")
            self.wb_blue_slider.setEnabled(False)

        # Start the IC4CameraThread
        self.ic4_thread = IC4CameraThread(self.ic4_ctrl.sink)
        self.ic4_thread.frame_ready.connect(self.on_frame_ready)
        self.ic4_thread.start()

    def on_disconnect(self):
        """Stop the IC4 thread, teardown IC4, and reset UI."""
        if self.ic4_thread:
            self.ic4_thread.stop()
            self.ic4_thread = None

        if self.ic4_ctrl:
            self.ic4_ctrl.close()
            self.ic4_ctrl = None

        # Reset UI
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)

        self.ae_checkbox.setEnabled(False)
        self.wb_auto_checkbox.setEnabled(False)

        self.exposure_slider.setEnabled(False)
        self.gain_slider.setEnabled(False)
        self.brightness_slider.setEnabled(False)

        self.wb_red_slider.setEnabled(False)
        self.wb_blue_slider.setEnabled(False)

        self.opengl_widget.current_image = None
        self.opengl_widget.update()

    def on_toggle_ae(self, state):
        """User toggled Auto Exposure ON/OFF."""
        if not self.ic4_ctrl:
            return
        ae_on = state == Qt.Checked
        self.ic4_ctrl.set_auto_exposure(ae_on)
        # Enable manual sliders only if AE is off
        enabled = not ae_on
        self.exposure_slider.setEnabled(enabled)
        self.gain_slider.setEnabled(enabled)
        self.brightness_slider.setEnabled(enabled)

    def on_exposure_change(self, val):
        """User dragged the Exposure slider."""
        if not self.ic4_ctrl:
            return
        self.ic4_ctrl.set_exposure(val)
        self.exposure_label.setText(f"Exposure: {val}")

    def on_gain_change(self, val):
        """User dragged the Gain slider."""
        if not self.ic4_ctrl:
            return
        self.ic4_ctrl.set_gain(val)
        self.gain_label.setText(f"Gain: {val}")

    def on_brightness_change(self, val):
        """User dragged the Brightness slider."""
        if not self.ic4_ctrl:
            return
        self.ic4_ctrl.set_brightness(val)
        self.brightness_label.setText(f"Brightness: {val}")

    def on_toggle_wb_auto(self, state):
        """User toggled Auto White Balance ON/OFF."""
        if not self.ic4_ctrl:
            return
        wb_on = state == Qt.Checked
        self.ic4_ctrl.set_auto_white_balance(wb_on)
        enabled = not wb_on
        self.wb_red_slider.setEnabled(enabled)
        self.wb_blue_slider.setEnabled(enabled)

    def on_wb_red_change(self, val):
        """User dragged WB Red slider."""
        if not self.ic4_ctrl:
            return
        # Always disable auto WB when user picks a manual red
        self.ic4_ctrl.set_auto_white_balance(False)
        curr_b = self.ic4_ctrl.get_current_white_balance()[1]
        self.ic4_ctrl.set_white_balance(red=val, blue=curr_b)
        self.wb_red_label.setText(f"WB Red: {val}")

    def on_wb_blue_change(self, val):
        """User dragged WB Blue slider."""
        if not self.ic4_ctrl:
            return
        self.ic4_ctrl.set_auto_white_balance(False)
        curr_r = self.ic4_ctrl.get_current_white_balance()[0]
        self.ic4_ctrl.set_white_balance(red=curr_r, blue=val)
        self.wb_blue_label.setText(f"WB Blue: {val}")

    def on_frame_ready(self, np_img):
        """
        Receive a NumPy array (H×W×C), pass to OpenGL widget for rendering.
        """
        self.opengl_widget.update_frame(np_img)

    def closeEvent(self, event):
        """
        When the window is closed, ensure we disconnect the camera cleanly.
        """
        self.on_disconnect()
        event.accept()


def main():
    app = QApplication(sys.argv)
    win = CameraAppMainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
