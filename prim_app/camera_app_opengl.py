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
    QOpenGLWidget,  # QOpenGLWidget comes from QtWidgets in PyQt5
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPainter

# NumPy for array handling (used by ImageBuffer.numpy_wrap())
import numpy as np


class IC4CameraController:
    """
    Wraps the IC4 Grabber + QueueSink workflow to detect, open, and control DMK cameras.

    - Uses DeviceEnum.devices() to list cameras.
    - Opens the first DMK 33UX250 / 33UP5000 (or falls back to the first device).
    - Configures AcquisitionMode="Continuous" and AcquisitionFrameRate=10.0.
    - Creates a QueueSink with a SinkListener, allocates buffers, and starts streaming.
    - Exposes methods to get/set Auto Exposure, Exposure, Gain, Brightness,
      Auto White Balance, WhiteBalance Red, and WhiteBalance Blue using PropInteger / PropBoolean.
    """

    def __init__(self, preferred_models=None):
        # By default, look for these substrings in DeviceInfo.model_name
        self.preferred_models = preferred_models or ["DMK 33UX250", "DMK 33UP5000"]
        self.grabber = None
        self.sink = None
        self.listener = None

    def list_devices(self):
        """
        Return a list of DeviceInfo objects for all video capture devices.
        Use DeviceInfo.model_name, DeviceInfo.display_name, etc.
        """
        return ic4.DeviceEnum.devices()

    def open(self):
        """
        1. Initialize the IC4 library.
        2. Enumerate devices, pick the first matching preferred model (or fallback to the first).
        3. Open via Grabber.device_open().
        4. Set AcquisitionMode="Continuous" and AcquisitionFrameRate=10.0.
        5. Create a SinkListener and QueueSink(listener), attach it, and start acquisition.
        Returns True on success, False on any failure.
        """
        try:
            ic4.Library.init()  # Must be called once per process
        except ic4.IC4Exception as e:
            QMessageBox.critical(None, "IC4 Error", f"Library.init() failed:\n{e}")
            return False

        try:
            devices = ic4.DeviceEnum.devices()
        except ic4.IC4Exception as e:
            QMessageBox.critical(
                None, "IC4 Error", f"Failed to enumerate devices:\n{e}"
            )
            return False

        if len(devices) == 0:
            QMessageBox.critical(None, "Camera Error", "No IC4 devices found.")
            return False

        # Choose the first preferred model, else fallback to devices[0]
        chosen_info = None
        for info in devices:
            name = info.model_name  # e.g., "DMK 33UX250"
            for pref in self.preferred_models:
                if pref in name:
                    chosen_info = info
                    break
            if chosen_info:
                break
        if chosen_info is None:
            chosen_info = devices[0]

        # Create and open the Grabber
        try:
            self.grabber = ic4.Grabber()
            self.grabber.device_open(chosen_info)
        except ic4.IC4Exception as e:
            QMessageBox.critical(None, "IC4 Error", f"Failed to open device:\n{e}")
            return False

        # Configure Acquisition Mode = "Continuous" and frame rate = 10.0
        pm = self.grabber.device_property_map
        try:
            pm.set_value(ic4.PropId.ACQUISITION_MODE, "Continuous")
            pm.set_value(ic4.PropId.ACQUISITION_FRAME_RATE, 10.0)
        except ic4.IC4Exception:
            # Some cameras may not support setting frame rate explicitly;
            # if it fails, we proceed with defaults.
            pass

        # Create a SinkListener (needed by QueueSink) and the QueueSink itself
        try:
            self.listener = ic4.SinkListener()
            self.sink = ic4.QueueSink(self.listener)
            # Attach and start acquisition immediately
            self.grabber.stream_setup(
                self.sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START
            )
            # Pre-allocate 10 buffers to minimize drops
            self.sink.alloc_and_queue_buffers(10)
        except ic4.IC4Exception as e:
            QMessageBox.critical(
                None, "IC4 Error", f"Failed to create or attach QueueSink:\n{e}"
            )
            self.close()
            return False

        return True

    def close(self):
        """Stop acquisition, close the device, and release Grabber & Sink."""
        if self.grabber:
            try:
                self.grabber.acquisition_stop()
            except:
                pass
            try:
                self.grabber.device_close()
            except:
                pass
        self.grabber = None
        self.sink = None
        self.listener = None

    def __del__(self):
        self.close()

    # ----------------------------
    # PROPERTY-QUERY HELPERS
    # ----------------------------

    def _get_integer_property(self, prop_id):
        """
        Return a PropInteger object for the given prop_id (e.g., PropId.EXPOSURE, PropId.GAIN_RAW, etc.).
        Returns None if not found.
        """
        pm = self.grabber.device_property_map
        try:
            return pm.find_integer(prop_id)
        except ic4.IC4Exception:
            return None

    def _get_boolean_property(self, prop_id):
        """
        Return a PropBoolean object for the given prop_id (e.g., PropId.EXPOSURE_AUTO).
        Returns None if not found.
        """
        pm = self.grabber.device_property_map
        try:
            return pm.find_boolean(prop_id)
        except ic4.IC4Exception:
            return None

    def _get_auto_property(self, auto_id):
        """
        Return either a PropBoolean or PropEnumeration for an "Auto" feature.
        E.g. PropId.EXPOSURE_AUTO or PropId.WHITE_BALANCE_AUTO.
        """
        # Try Boolean first
        prop_bool = self._get_boolean_property(auto_id)
        if prop_bool:
            return prop_bool
        # Fallback to enumeration
        pm = self.grabber.device_property_map
        try:
            return pm.find_enumeration(auto_id)
        except ic4.IC4Exception:
            return None

    def get_auto_exposure(self) -> bool:
        """Return True if Auto Exposure is ON."""
        prop = self._get_auto_property(ic4.PropId.EXPOSURE_AUTO)
        if not prop:
            return False
        try:
            return bool(prop.value)
        except:
            return False

    def set_auto_exposure(self, enabled: bool):
        """Toggle Auto Exposure ON/OFF."""
        prop = self._get_auto_property(ic4.PropId.EXPOSURE_AUTO)
        if not prop:
            return
        try:
            prop.value = bool(enabled)
        except ic4.IC4Exception:
            pass

    def get_exposure_range(self):
        """
        Return a sorted list of valid Exposure values (PropInteger.valid_value_set).
        """
        prop = self._get_integer_property(ic4.PropId.EXPOSURE)
        if not prop:
            return []
        try:
            return sorted(list(prop.valid_value_set))
        except:
            return []

    def get_current_exposure(self) -> int:
        """Return the current Exposure value as an integer."""
        prop = self._get_integer_property(ic4.PropId.EXPOSURE)
        if not prop:
            return 0
        try:
            return int(prop.value)
        except:
            return 0

    def set_exposure(self, value: int):
        """Turn off Auto Exposure, then set Exposure to the given value."""
        self.set_auto_exposure(False)
        prop = self._get_integer_property(ic4.PropId.EXPOSURE)
        if not prop:
            return
        try:
            prop.value = int(value)
        except ic4.IC4Exception:
            pass

    def get_gain_range(self):
        """
        Return a sorted list of valid Gain values. Some cameras expose GAIN_RAW.
        Fallback to PropId.GAIN if GAIN_RAW is not found.
        """
        prop = self._get_integer_property(
            ic4.PropId.GAIN_RAW
        ) or self._get_integer_property(ic4.PropId.GAIN)
        if not prop:
            return []
        try:
            return sorted(list(prop.valid_value_set))
        except:
            return []

    def get_current_gain(self) -> int:
        """Return the current Gain (either GAIN_RAW or GAIN)."""
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
        """Set Gain (or GainRaw) to the given integer value."""
        prop = self._get_integer_property(
            ic4.PropId.GAIN_RAW
        ) or self._get_integer_property(ic4.PropId.GAIN)
        if not prop:
            return
        try:
            prop.value = int(value)
        except ic4.IC4Exception:
            pass

    def get_brightness_range(self):
        """
        Return a sorted list of valid Brightness values (PropInteger.valid_value_set).
        """
        prop = self._get_integer_property(ic4.PropId.BRIGHTNESS)
        if not prop:
            return []
        try:
            return sorted(list(prop.valid_value_set))
        except:
            return []

    def get_current_brightness(self) -> int:
        """Return the current Brightness as an integer."""
        prop = self._get_integer_property(ic4.PropId.BRIGHTNESS)
        if not prop:
            return 0
        try:
            return int(prop.value)
        except:
            return 0

    def set_brightness(self, value: int):
        """Set Brightness to the given integer value."""
        prop = self._get_integer_property(ic4.PropId.BRIGHTNESS)
        if not prop:
            return
        try:
            prop.value = int(value)
        except ic4.IC4Exception:
            pass

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
        """Toggle Auto White Balance ON/OFF."""
        prop = self._get_auto_property(ic4.PropId.WHITE_BALANCE_AUTO)
        if not prop:
            return
        try:
            prop.value = bool(enabled)
        except ic4.IC4Exception:
            pass

    def get_white_balance_range(self):
        """
        Return two sorted lists: valid Red values and valid Blue values.
        Uses PropId.WHITE_BALANCE_RED and PropId.WHITE_BALANCE_BLUE.
        """
        red_prop = self._get_integer_property(ic4.PropId.WHITE_BALANCE_RED)
        blue_prop = self._get_integer_property(ic4.PropId.WHITE_BALANCE_BLUE)
        reds = sorted(list(red_prop.valid_value_set)) if red_prop else []
        blues = sorted(list(blue_prop.valid_value_set)) if blue_prop else []
        return reds, blues

    def get_current_white_balance(self):
        """
        Return a tuple (current_red, current_blue) as integers.
        """
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
        Turn off Auto White Balance, then set the Red and Blue channels.
        """
        self.set_auto_white_balance(False)
        red_prop = self._get_integer_property(ic4.PropId.WHITE_BALANCE_RED)
        blue_prop = self._get_integer_property(ic4.PropId.WHITE_BALANCE_BLUE)
        try:
            if red_prop:
                red_prop.value = int(red)
            if blue_prop:
                blue_prop.value = int(blue)
        except ic4.IC4Exception:
            pass


class IC4CameraThread(QThread):
    """
    QThread that continuously pops the newest ImageBuffer from a QueueSink
    and emits a NumPy array for display.
    """

    frame_ready = pyqtSignal(object)  # emits a NumPy ndarray

    def __init__(self, sink: ic4.QueueSink, parent=None):
        super().__init__(parent)
        self.sink = sink
        self._running = False

    def run(self):
        self._running = True
        while self._running:
            try:
                buf = self.sink.try_pop_output_buffer()  # non-blocking
            except ic4.IC4Exception as e:
                print(f"[IC4Thread] Error popping buffer: {e}")
                buf = None

            if buf is None:
                time.sleep(0.001)
                continue

            try:
                # numpy_wrap() returns a memoryview over the buffer’s data
                arr = buf.numpy_wrap()  # may be uint8 or uint16, (H, W, C)
                np_img = np.array(arr, copy=False)
                self.frame_ready.emit(np_img)
            except Exception as e:
                print(f"[IC4Thread] Failed to numpy_wrap(): {e}")
            finally:
                try:
                    buf.release()  # return the buffer to the free queue
                except:
                    pass

    def stop(self):
        """Stop the thread’s loop and wait for it to finish."""
        self._running = False
        self.wait()


class CameraOpenGLWidget(QOpenGLWidget):
    """
    A QOpenGLWidget that draws incoming NumPy frames using QPainter.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.current_image = None  # holds a QImage for painting

    def update_frame(self, np_img):
        """
        Convert a NumPy array (H×W×C, dtype=uint8 or uint16) to QImage,
        scale it to fit the widget (keeping aspect ratio), and schedule a repaint.
        """
        if np_img is None:
            return

        h, w, c = np_img.shape

        # Handle 16-bit grayscale by downshifting to 8-bit
        if np_img.dtype == np.uint16 and c == 1:
            arr8 = (np_img >> 8).astype(np.uint8)
            image = QImage(arr8.data, w, h, w, QImage.Format_Grayscale8)

        # 8-bit single-channel → QImage.Format_Grayscale8
        elif np_img.dtype == np.uint8 and c == 1:
            image = QImage(np_img.data, w, h, w, QImage.Format_Grayscale8)

        # 8-bit BGR → convert to RGB888
        elif np_img.dtype == np.uint8 and c == 3:
            rgb = np_img[..., ::-1]  # BGR→RGB
            bytes_per_line = 3 * w
            image = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)

        # 8-bit BGRA → convert to RGBA
        elif np_img.dtype == np.uint8 and c == 4:
            rgba = np_img[..., [2, 1, 0, 3]]
            bytes_per_line = 4 * w
            image = QImage(rgba.data, w, h, bytes_per_line, QImage.Format_RGBA8888)

        else:
            # Fallback: convert to grayscale 8-bit
            gray = (np_img[..., 0] if c > 1 else np_img).astype(np.uint8)
            image = QImage(gray.data, w, h, w, QImage.Format_Grayscale8)

        # Scale to fit widget, preserving aspect ratio
        self.current_image = image.scaled(
            self.width(), self.height(), Qt.KeepAspectRatio
        )
        self.update()

    def paintGL(self):
        """
        Called whenever Qt repaints this widget. We draw the current QImage centered.
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
        On resize, re‐scale the current image (if any) to fit the new size.
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
        # Central widget & horizontal layout
        central = QWidget()
        main_layout = QHBoxLayout()
        central.setLayout(main_layout)
        self.setCentralWidget(central)

        # Left side: OpenGL preview
        self.opengl_widget = CameraOpenGLWidget()
        main_layout.addWidget(self.opengl_widget)

        # Right side: Controls
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

        # Manual Exposure slider + label
        self.exposure_label = QLabel("Exposure: N/A")
        self.exposure_slider = QSlider(Qt.Horizontal)
        self.exposure_slider.setEnabled(False)
        self.exposure_slider.valueChanged.connect(self.on_exposure_change)
        ae_layout.addWidget(self.exposure_label)
        ae_layout.addWidget(self.exposure_slider)

        # Gain slider + label
        self.gain_label = QLabel("Gain: N/A")
        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setEnabled(False)
        self.gain_slider.valueChanged.connect(self.on_gain_change)
        ae_layout.addWidget(self.gain_label)
        ae_layout.addWidget(self.gain_slider)

        # Brightness slider + label
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

        # Manual WB Red slider + label
        self.wb_red_label = QLabel("WB Red: N/A")
        self.wb_red_slider = QSlider(Qt.Horizontal)
        self.wb_red_slider.setEnabled(False)
        self.wb_red_slider.valueChanged.connect(self.on_wb_red_change)
        wb_layout.addWidget(self.wb_red_label)
        wb_layout.addWidget(self.wb_red_slider)

        # Manual WB Blue slider + label
        self.wb_blue_label = QLabel("WB Blue: N/A")
        self.wb_blue_slider = QSlider(Qt.Horizontal)
        self.wb_blue_slider.setEnabled(False)
        self.wb_blue_slider.valueChanged.connect(self.on_wb_blue_change)
        wb_layout.addWidget(self.wb_blue_label)
        wb_layout.addWidget(self.wb_blue_slider)

        # Spacer so controls stay at top
        controls_layout.addStretch()

    def on_connect(self):
        """
        When “Connect Camera” is clicked:
         1. Instantiate IC4CameraController and open the camera.
         2. If successful, populate each slider’s range/value from valid_value_set.
         3. Start IC4CameraThread to receive frames and display them.
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

        # Enable AE / WB checkboxes
        self.ae_checkbox.setEnabled(True)
        self.wb_auto_checkbox.setEnabled(True)

        # Initialize AE checkbox state
        self.ae_checkbox.setChecked(self.ic4_ctrl.get_auto_exposure())

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
        r_vals, bl_vals = self.ic4_ctrl.get_white_balance_range()
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

            enabled_manual_wb = not self.ic4_ctrl.get_auto_white_balance()
            self.wb_red_slider.setEnabled(enabled_manual_wb)
            self.wb_blue_slider.setEnabled(enabled_manual_wb)
        else:
            self.wb_auto_checkbox.setEnabled(False)
            self.wb_red_label.setText("WB Red: N/A")
            self.wb_red_slider.setEnabled(False)
            self.wb_blue_label.setText("WB Blue: N/A")
            self.wb_blue_slider.setEnabled(False)

        # Start the IC4CameraThread to pull frames and emit them
        self.ic4_thread = IC4CameraThread(self.ic4_ctrl.sink)
        self.ic4_thread.frame_ready.connect(self.on_frame_ready)
        self.ic4_thread.start()

    def on_disconnect(self):
        """Stop the IC4 thread, close the camera, and reset UI state."""
        if self.ic4_thread:
            self.ic4_thread.stop()
            self.ic4_thread = None

        if self.ic4_ctrl:
            self.ic4_ctrl.close()
            self.ic4_ctrl = None

        # Reset all UI elements
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
        # Enable manual sliders only if AE = off
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
        """User dragged the White Balance Red slider."""
        if not self.ic4_ctrl:
            return
        self.ic4_ctrl.set_auto_white_balance(False)
        curr_r, curr_b = self.ic4_ctrl.get_current_white_balance()
        self.ic4_ctrl.set_white_balance(red=val, blue=curr_b)
        self.wb_red_label.setText(f"WB Red: {val}")

    def on_wb_blue_change(self, val):
        """User dragged the White Balance Blue slider."""
        if not self.ic4_ctrl:
            return
        self.ic4_ctrl.set_auto_white_balance(False)
        curr_r, curr_b = self.ic4_ctrl.get_current_white_balance()
        self.ic4_ctrl.set_white_balance(red=curr_r, blue=val)
        self.wb_blue_label.setText(f"WB Blue: {val}")

    def on_frame_ready(self, np_img):
        """
        Receive a new NumPy frame (H×W×C), pass it to the OpenGL widget.
        """
        self.opengl_widget.update_frame(np_img)

    def closeEvent(self, event):
        """
        Ensure we disconnect the camera cleanly when the window closes.
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
