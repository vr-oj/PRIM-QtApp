# File: camera_app_opengl.py

import sys
import time
import threading

# IC4 SDK for camera control
import imagingcontrol4 as ic4

# OpenCV for video capture
import cv2

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
    QOpenGLWidget,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPainter


class IC4CameraController:
    """
    Wraps IC Imaging Control 4 (IC4) SDK to detect, open, and control DMK cameras.

    - Automatically picks the first matching DMK device (33UX250 or 33UP5000).
    - Selects the highest‐resolution format >= 10 FPS.
    - Exposes methods to toggle Auto Exposure, set Exposure, Gain, Brightness,
      and (if supported) White Balance.
    """

    def __init__(self, preferred_models=None):
        # By default, look for these substrings in the device name
        self.preferred_models = preferred_models or ["DMK 33UX250", "DMK 33UP5000"]
        self.device_list = None
        self.controller = None
        self.video_capture_index = None

    def list_devices(self):
        """Return a list of (index, name) for all IC4‐enumerated devices."""
        dev_list = ic4.DeviceList()
        devices = []
        for idx in range(dev_list.DeviceCount):
            name = dev_list.DeviceName[idx]
            devices.append((idx, name))
        return devices

    def open(self):
        """
        Enumerate cameras, pick the first matching preferred model (or fallback to device 0).
        Returns True on success, False if no device found or open failed.
        """
        self.device_list = ic4.DeviceList()
        if self.device_list.DeviceCount == 0:
            QMessageBox.critical(None, "Camera Error", "No IC4 devices found.")
            return False

        chosen_idx = None
        for idx in range(self.device_list.DeviceCount):
            name = self.device_list.DeviceName[idx]
            for pref in self.preferred_models:
                if pref in name:
                    chosen_idx = idx
                    break
            if chosen_idx is not None:
                break

        if chosen_idx is None:
            # fallback to device 0
            chosen_idx = 0

        # Instantiate ICImagingControl headless (parent_handle=0)
        try:
            self.controller = ic4.ICImagingControl(parent_handle=0)
        except Exception as e:
            QMessageBox.critical(
                None, "IC4 Error", f"Failed to create ICImagingControl:\n{e}"
            )
            return False

        # Select device by DevicePath
        try:
            self.controller.Device = self.device_list[chosen_idx].DevicePath
        except Exception as e:
            QMessageBox.critical(None, "IC4 Error", f"Failed to select device:\n{e}")
            return False

        # Save DirectShow index for OpenCV to use
        self.video_capture_index = chosen_idx

        # Give camera a moment to settle
        time.sleep(0.2)

        # Choose the best format (max resolution with ≥10 FPS)
        self._set_best_format(target_fps=10)

        # Turn Auto Exposure ON by default
        self.set_auto_exposure(True)

        return True

    def _set_best_format(self, target_fps=10):
        """
        Scans all supported formats (width, height, fps) and picks the one with
        the largest (width × height) that can do ≥ target_fps. If none can do target_fps,
        picks the format with the highest FPS (largest area).
        """
        fc = self.controller.VideoCaptureDevice.FrameFormatCount
        formats = []
        for idx in range(fc):
            w = self.controller.VideoCaptureDevice.FrameFormatWidth[idx]
            h = self.controller.VideoCaptureDevice.FrameFormatHeight[idx]
            fps = self.controller.VideoCaptureDevice.FrameFormatFrameRate[idx]
            formats.append((w, h, fps, idx))

        # Filter for fps >= target_fps
        eligible = [f for f in formats if f[2] >= target_fps]
        if not eligible:
            eligible = formats  # fallback

        # Sort by area then fps, descending
        eligible.sort(key=lambda x: (x[0] * x[1], x[2]), reverse=True)
        best = eligible[0]
        best_idx = best[3]
        bw, bh, bf = best[0], best[1], best[2]

        # Apply it
        self.controller.VideoCaptureDevice.FrameFormat = best_idx
        print(f"[IC4] Using format: {bw}×{bh} @ {bf} FPS (index {best_idx})")
        time.sleep(0.1)  # let it settle

    def set_auto_exposure(self, enabled: bool):
        """Toggle Auto Exposure ON (True) or OFF (False)."""
        if not self.controller:
            return
        try:
            self.controller.AutoExposure = 1 if enabled else 0
        except Exception as e:
            print(f"[IC4] AutoExposure error: {e}")

    def get_auto_exposure(self) -> bool:
        """Returns True if AutoExposure is ON."""
        if not self.controller:
            return False
        try:
            return bool(self.controller.AutoExposure)
        except:
            return False

    def get_exposure_range(self):
        """Return (min, max, increment) for manual Exposure."""
        if not self.controller:
            return (0, 0, 1)
        try:
            return (
                self.controller.ExposureMin,
                self.controller.ExposureMax,
                self.controller.ExposureIncrement,
            )
        except:
            return (0, 0, 1)

    def get_current_exposure(self) -> int:
        """Return the current Exposure value."""
        if not self.controller:
            return 0
        try:
            return self.controller.Exposure
        except:
            return 0

    def set_exposure(self, value: int):
        """Set manual exposure (in microseconds or IC4 units). AutoExposure will be turned OFF."""
        if not self.controller:
            return
        try:
            self.set_auto_exposure(False)
            self.controller.Exposure = value
        except Exception as e:
            print(f"[IC4] SetExposure error: {e}")

    def get_gain_range(self):
        """Return (min, max, increment) for Gain."""
        if not self.controller:
            return (0, 0, 1)
        try:
            return (
                self.controller.GainMin,
                self.controller.GainMax,
                self.controller.GainIncrement,
            )
        except:
            return (0, 0, 1)

    def get_current_gain(self) -> int:
        """Return current Gain."""
        if not self.controller:
            return 0
        try:
            return self.controller.Gain
        except:
            return 0

    def set_gain(self, value: int):
        """Set manual Gain. Only valid when AutoExposure is OFF."""
        if not self.controller:
            return
        try:
            self.controller.Gain = value
        except Exception as e:
            print(f"[IC4] SetGain error: {e}")

    def get_brightness_range(self):
        """Return (min, max, increment) for Brightness."""
        if not self.controller:
            return (0, 0, 1)
        try:
            return (
                self.controller.BrightnessMin,
                self.controller.BrightnessMax,
                self.controller.BrightnessIncrement,
            )
        except:
            return (0, 0, 1)

    def get_current_brightness(self) -> int:
        """Return current Brightness."""
        if not self.controller:
            return 0
        try:
            return self.controller.Brightness
        except:
            return 0

    def set_brightness(self, value: int):
        """Set manual Brightness."""
        if not self.controller:
            return
        try:
            self.controller.Brightness = value
        except Exception as e:
            print(f"[IC4] SetBrightness error: {e}")

    def get_white_balance_range(self):
        """
        Return ((r_min, r_max, r_inc), (b_min, b_max, b_inc)) for WhiteBalanceRed / WhiteBalanceBlue.
        If not supported, returns ((0,0,1),(0,0,1)).
        """
        if not self.controller:
            return ((0, 0, 1), (0, 0, 1))
        try:
            return (
                (
                    self.controller.WhiteBalanceRedMin,
                    self.controller.WhiteBalanceRedMax,
                    self.controller.WhiteBalanceRedIncrement,
                ),
                (
                    self.controller.WhiteBalanceBlueMin,
                    self.controller.WhiteBalanceBlueMax,
                    self.controller.WhiteBalanceBlueIncrement,
                ),
            )
        except:
            return ((0, 0, 1), (0, 0, 1))

    def get_white_balance_auto(self) -> bool:
        """Return True if WhiteBalanceAuto is ON."""
        if not self.controller:
            return False
        try:
            return bool(self.controller.WhiteBalanceAuto)
        except:
            return False

    def set_white_balance_auto(self, enabled: bool):
        """Toggle WhiteBalanceAuto ON (True) or OFF (False)."""
        if not self.controller:
            return
        try:
            self.controller.WhiteBalanceAuto = 1 if enabled else 0
        except Exception as e:
            print(f"[IC4] SetWhiteBalanceAuto error: {e}")

    def set_white_balance(self, red: int, blue: int):
        """
        Manually set White Balance Red / Blue (only if WB Auto = OFF).
        """
        if not self.controller:
            return
        try:
            self.controller.WhiteBalanceAuto = 0
            self.controller.WhiteBalanceRed = red
            self.controller.WhiteBalanceBlue = blue
        except Exception as e:
            print(f"[IC4] SetWhiteBalance error: {e}")

    def close(self):
        """Stop any live, then close the IC4 controller."""
        if self.controller:
            try:
                self.controller.LiveStop()
            except:
                pass
            try:
                self.controller.Close()
            except:
                pass
        self.controller = None

    def __del__(self):
        self.close()


class OpenCVCameraThread(QThread):
    """
    QThread that captures frames from OpenCV (cv2.VideoCapture) and emits them as NumPy arrays.
    """

    frame_ready = pyqtSignal(object)

    def __init__(self, cam_index=0, parent=None):
        super().__init__(parent)
        self.cam_index = cam_index
        self._running = False

    def run(self):
        cap = cv2.VideoCapture(self.cam_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            print(f"[OpenCV] Failed to open camera index {self.cam_index}")
            return

        self._running = True
        while self._running:
            ret, frame = cap.read()
            if not ret:
                continue
            self.frame_ready.emit(frame)
        cap.release()

    def stop(self):
        self._running = False
        self.wait()


class CameraOpenGLWidget(QOpenGLWidget):
    """
    A QOpenGLWidget that draws incoming frames (as NumPy arrays) using QPainter.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.current_image = None  # QImage to hold the latest frame

    def update_frame(self, frame):
        """
        Convert the incoming BGR frame (NumPy array) to QImage and schedule a repaint.
        """
        # Convert BGR (OpenCV) to RGB
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        # Create QImage from the raw data; use Format_RGB888
        image = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        # Scale image to widget’s size, keeping aspect ratio
        self.current_image = image.scaled(
            self.width(), self.height(), Qt.KeepAspectRatio
        )
        # Trigger a repaint
        self.update()

    def paintGL(self):
        """
        Draw the current QImage (if any) using QPainter.
        """
        self.makeCurrent()
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.black)
        if self.current_image is not None:
            # Center the image
            x = (self.width() - self.current_image.width()) // 2
            y = (self.height() - self.current_image.height()) // 2
            painter.drawImage(x, y, self.current_image)
        painter.end()

    def resizeGL(self, w, h):
        """
        When the widget is resized, re‐scale the current image (if any).
        """
        if self.current_image:
            self.current_image = self.current_image.scaled(w, h, Qt.KeepAspectRatio)


class CameraAppMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Standalone IC4 Camera App (OpenGL)")
        self.setGeometry(200, 200, 1000, 600)

        self.ic4_ctrl = None
        self.cv_thread = None

        # Build UI
        self._build_ui()

    def _build_ui(self):
        # Central widget & layout
        central = QWidget()
        main_layout = QHBoxLayout()
        central.setLayout(main_layout)
        self.setCentralWidget(central)

        # Left side: OpenGL video feed
        self.opengl_widget = CameraOpenGLWidget()
        main_layout.addWidget(self.opengl_widget)

        # Right side: Controls
        controls_container = QWidget()
        controls_layout = QVBoxLayout()
        controls_container.setLayout(controls_layout)
        main_layout.addWidget(controls_container)

        # --- Connection Buttons ---
        self.connect_btn = QPushButton("Connect Camera")
        self.connect_btn.clicked.connect(self.on_connect)
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self.on_disconnect)
        self.disconnect_btn.setEnabled(False)

        controls_layout.addWidget(self.connect_btn)
        controls_layout.addWidget(self.disconnect_btn)

        # --- Auto Exposure ---
        ae_group = QGroupBox("Exposure Control")
        ae_layout = QVBoxLayout()
        ae_group.setLayout(ae_layout)
        controls_layout.addWidget(ae_group)

        self.ae_checkbox = QCheckBox("Auto Exposure")
        self.ae_checkbox.setChecked(True)
        self.ae_checkbox.setEnabled(False)
        self.ae_checkbox.stateChanged.connect(self.on_toggle_ae)
        ae_layout.addWidget(self.ae_checkbox)

        # Manual Exposure slider
        self.exposure_slider = QSlider(Qt.Horizontal)
        self.exposure_slider.setEnabled(False)
        self.exposure_slider.valueChanged.connect(self.on_exposure_change)
        self.exposure_label = QLabel("Exposure: N/A")
        ae_layout.addWidget(self.exposure_label)
        ae_layout.addWidget(self.exposure_slider)

        # Gain slider
        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setEnabled(False)
        self.gain_slider.valueChanged.connect(self.on_gain_change)
        self.gain_label = QLabel("Gain: N/A")
        ae_layout.addWidget(self.gain_label)
        ae_layout.addWidget(self.gain_slider)

        # Brightness slider
        self.brightness_slider = QSlider(Qt.Horizontal)
        self.brightness_slider.setEnabled(False)
        self.brightness_slider.valueChanged.connect(self.on_brightness_change)
        self.brightness_label = QLabel("Brightness: N/A")
        ae_layout.addWidget(self.brightness_label)
        ae_layout.addWidget(self.brightness_slider)

        # --- White Balance ---
        wb_group = QGroupBox("White Balance")
        wb_layout = QVBoxLayout()
        wb_group.setLayout(wb_layout)
        controls_layout.addWidget(wb_group)

        self.wb_auto_checkbox = QCheckBox("Auto White Balance")
        self.wb_auto_checkbox.setChecked(True)
        self.wb_auto_checkbox.setEnabled(False)
        self.wb_auto_checkbox.stateChanged.connect(self.on_toggle_wb_auto)
        wb_layout.addWidget(self.wb_auto_checkbox)

        # Manual WB sliders (Red / Blue)
        self.wb_red_slider = QSlider(Qt.Horizontal)
        self.wb_red_slider.setEnabled(False)
        self.wb_red_slider.valueChanged.connect(self.on_wb_red_change)
        self.wb_red_label = QLabel("WB Red: N/A")
        wb_layout.addWidget(self.wb_red_label)
        wb_layout.addWidget(self.wb_red_slider)

        self.wb_blue_slider = QSlider(Qt.Horizontal)
        self.wb_blue_slider.setEnabled(False)
        self.wb_blue_slider.valueChanged.connect(self.on_wb_blue_change)
        self.wb_blue_label = QLabel("WB Blue: N/A")
        wb_layout.addWidget(self.wb_blue_label)
        wb_layout.addWidget(self.wb_blue_slider)

        # Spacer to push controls upward
        controls_layout.addStretch()

    def on_connect(self):
        """
        Called when the user clicks "Connect Camera":
         - Instantiate IC4 controller and open the first supported camera.
         - If successful, enable all controls, query property ranges, and start OpenCV thread.
        """
        self.ic4_ctrl = IC4CameraController(
            preferred_models=["DMK 33UX250", "DMK 33UP5000"]
        )
        success = self.ic4_ctrl.open()
        if not success:
            return

        # Enable/disable appropriate buttons & checkboxes
        self.connect_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(True)
        self.ae_checkbox.setEnabled(True)
        self.wb_auto_checkbox.setEnabled(True)
        self.ae_checkbox.setChecked(True)
        self.wb_auto_checkbox.setChecked(True)

        # Query and populate Exposure range
        e_min, e_max, e_inc = self.ic4_ctrl.get_exposure_range()
        self.exposure_slider.setMinimum(e_min)
        self.exposure_slider.setMaximum(e_max)
        self.exposure_slider.setSingleStep(e_inc)
        current_e = self.ic4_ctrl.get_current_exposure()
        self.exposure_slider.setValue(current_e)
        self.exposure_label.setText(f"Exposure: {current_e}")

        # Query and populate Gain range
        g_min, g_max, g_inc = self.ic4_ctrl.get_gain_range()
        self.gain_slider.setMinimum(g_min)
        self.gain_slider.setMaximum(g_max)
        self.gain_slider.setSingleStep(g_inc)
        current_g = self.ic4_ctrl.get_current_gain()
        self.gain_slider.setValue(current_g)
        self.gain_label.setText(f"Gain: {current_g}")

        # Query and populate Brightness range
        b_min, b_max, b_inc = self.ic4_ctrl.get_brightness_range()
        self.brightness_slider.setMinimum(b_min)
        self.brightness_slider.setMaximum(b_max)
        self.brightness_slider.setSingleStep(b_inc)
        current_b = self.ic4_ctrl.get_current_brightness()
        self.brightness_slider.setValue(current_b)
        self.brightness_label.setText(f"Brightness: {current_b}")

        # Query and populate WB ranges
        (r_min, r_max, r_inc), (bl_min, bl_max, bl_inc) = (
            self.ic4_ctrl.get_white_balance_range()
        )
        # If WB range is (0,0,1), assume unsupported
        if (r_min, r_max) == (0, 0):
            self.wb_auto_checkbox.setEnabled(False)
            self.wb_red_slider.setEnabled(False)
            self.wb_blue_slider.setEnabled(False)
            self.wb_red_label.setText("WB Red: N/A")
            self.wb_blue_label.setText("WB Blue: N/A")
        else:
            self.wb_red_slider.setMinimum(r_min)
            self.wb_red_slider.setMaximum(r_max)
            self.wb_red_slider.setSingleStep(r_inc)
            current_red = getattr(self.ic4_ctrl.controller, "WhiteBalanceRed", 0)
            self.wb_red_slider.setValue(current_red)
            self.wb_red_label.setText(f"WB Red: {current_red}")

            self.wb_blue_slider.setMinimum(bl_min)
            self.wb_blue_slider.setMaximum(bl_max)
            self.wb_blue_slider.setSingleStep(bl_inc)
            current_blue = getattr(self.ic4_ctrl.controller, "WhiteBalanceBlue", 0)
            self.wb_blue_slider.setValue(current_blue)
            self.wb_blue_label.setText(f"WB Blue: {current_blue}")

        # Because AE and WB Auto are ON by default, disable manual sliders initially
        self._set_manual_exposure_controls(enabled=False)
        self._set_manual_wb_controls(enabled=False)

        # Start OpenCV thread
        cam_idx = self.ic4_ctrl.video_capture_index
        self.cv_thread = OpenCVCameraThread(cam_index=cam_idx)
        self.cv_thread.frame_ready.connect(self.on_frame_ready)
        self.cv_thread.start()

    def on_disconnect(self):
        """Stop the OpenCV thread and close IC4, then reset UI."""
        if self.cv_thread:
            self.cv_thread.stop()
            self.cv_thread = None

        if self.ic4_ctrl:
            self.ic4_ctrl.close()
            self.ic4_ctrl = None

        # Reset UI
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.ae_checkbox.setEnabled(False)
        self.wb_auto_checkbox.setEnabled(False)
        self._set_manual_exposure_controls(enabled=False)
        self._set_manual_wb_controls(enabled=False)
        self.opengl_widget.current_image = None
        self.opengl_widget.update()

    def on_toggle_ae(self, state):
        """User toggled Auto Exposure ON/OFF."""
        if not self.ic4_ctrl:
            return
        ae_on = state == Qt.Checked
        self.ic4_ctrl.set_auto_exposure(ae_on)
        self._set_manual_exposure_controls(enabled=not ae_on)

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
        self.ic4_ctrl.set_white_balance_auto(wb_on)
        self._set_manual_wb_controls(enabled=not wb_on)

    def on_wb_red_change(self, val):
        """User dragged WB Red slider."""
        if not self.ic4_ctrl:
            return
        self.ic4_ctrl.set_white_balance_auto(False)
        current_blue = getattr(self.ic4_ctrl.controller, "WhiteBalanceBlue", 0)
        self.ic4_ctrl.set_white_balance(red=val, blue=current_blue)
        self.wb_red_label.setText(f"WB Red: {val}")

    def on_wb_blue_change(self, val):
        """User dragged WB Blue slider."""
        if not self.ic4_ctrl:
            return
        self.ic4_ctrl.set_white_balance_auto(False)
        current_red = getattr(self.ic4_ctrl.controller, "WhiteBalanceRed", 0)
        self.ic4_ctrl.set_white_balance(red=current_red, blue=val)
        self.wb_blue_label.setText(f"WB Blue: {val}")

    def on_frame_ready(self, frame):
        """
        Receive a BGR frame from OpenCV, pass it to the OpenGL widget for rendering.
        """
        self.opengl_widget.update_frame(frame)

    def _set_manual_exposure_controls(self, enabled: bool):
        """Enable/disable Exposure, Gain, Brightness sliders."""
        self.exposure_slider.setEnabled(enabled)
        self.gain_slider.setEnabled(enabled)
        self.brightness_slider.setEnabled(enabled)

    def _set_manual_wb_controls(self, enabled: bool):
        """Enable/disable White Balance Red/Blue sliders."""
        self.wb_red_slider.setEnabled(enabled)
        self.wb_blue_slider.setEnabled(enabled)


def main():
    app = QApplication(sys.argv)
    win = CameraAppMainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
