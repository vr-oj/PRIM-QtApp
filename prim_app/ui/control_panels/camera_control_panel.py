# PRIM-QTAPP/ui/control_panels/camera_control_panel.py

import logging
import threading

import imagingcontrol4 as ic4
from PyQt5.QtWidgets import (
    QWidget,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QSlider,
    QCheckBox,
    QSizePolicy,
    QMessageBox,
)
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot

log = logging.getLogger(__name__)


class CameraControlPanel(QWidget):
    """
    A dynamic control panel for IC4 camera properties.
    Builds sliders for all numeric properties (e.g., Gain, Brightness, Exposure, etc.)
    and a checkbox for Auto Exposure if supported.
    """

    # Emitted whenever a property is changed: (property_name:str, new_value:float)
    property_changed = pyqtSignal(str, float)

    # Emitted whenever auto-exposure is toggled: (True/False)
    auto_exposure_toggled = pyqtSignal(bool)

    def __init__(self, camera_thread=None, parent=None):
        super().__init__(parent)
        self.camera_thread = camera_thread
        self.grabber = None
        self.property_sliders = {}  # {PropId: (label_widget, slider_widget)}

        # Layout that will hold all dynamic controls
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(4, 4, 4, 4)
        self._main_layout.setSpacing(6)

        # Auto Exposure checkbox (added only if supported)
        self.ae_checkbox = None
        self._is_auto_exposure = False
        self._block_slider_signals = False

        # Build a placeholder message first
        self._placeholder = QLabel("No camera connected.", alignment=Qt.AlignCenter)
        self._placeholder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._main_layout.addWidget(self._placeholder)

        # If we already have a running camera thread, connect to its signal
        if self.camera_thread:
            # Some camera threads emit a custom signal when opened.
            # We'll assume camera_thread emits `started_grabber` once grabber is ready.
            try:
                self.camera_thread.grabber_ready.connect(self._on_grabber_ready)
            except Exception:
                # If no such signal, we can poll in a short thread after a delay
                threading.Timer(0.5, self._attempt_sync).start()

    def _attempt_sync(self):
        """
        If no explicit `grabber_ready` signal is available, we poll once.
        """
        if hasattr(self.camera_thread, "grabber") and self.camera_thread.grabber:
            self._on_grabber_ready()
        else:
            # If still not ready, try again a bit later
            threading.Timer(0.5, self._attempt_sync).start()

    @pyqtSlot()
    def _on_grabber_ready(self):
        """
        Called when SDKCameraThread has initialized `grabber` (camera opened).
        We can now query `grabber.device_property_map` for available properties.
        """
        # Remove placeholder text
        self._main_layout.removeWidget(self._placeholder)
        self._placeholder.deleteLater()
        self._placeholder = None

        self.grabber = self.camera_thread.grabber  # IC4 Grabber instance

        # Build dynamic UI
        self._build_dynamic_controls()

    def _build_dynamic_controls(self):
        """
        Inspect grabber.device_property_map.enumerate() to find all numeric properties,
        then create sliders for each one. Also create an Auto‐Exposure checkbox if supported.
        """
        if not self.grabber:
            return

        prop_map = self.grabber.device_property_map
        try:
            all_props = prop_map.enumerate()
        except ic4.IC4Exception as e:
            log.error(f"[CameraControlPanel] Could not enumerate properties: {e}")
            return

        # --- Auto Exposure Toggle ---
        # Many IC4 cameras expose `PropId.EXPOSURE_AUTO` or `PropId.GevExposureAuto`.
        ae_prop = None
        for p in all_props:
            if p.name.lower() in ["exposure_auto", "gevexposureauto"]:
                ae_prop = p
                break

        if ae_prop:
            self.ae_checkbox = QCheckBox("Auto Exposure")
            # Query current value:
            try:
                ae_value = prop_map.get_value(ae_prop.id)
                self._is_auto_exposure = bool(ae_value)
                self.ae_checkbox.setChecked(self._is_auto_exposure)
            except Exception as e:
                log.warning(f"[CameraControlPanel] Failed getting auto‐exposure: {e}")
                self._is_auto_exposure = True
                self.ae_checkbox.setChecked(True)

            # Enable/disable sliders based on AE
            self.ae_checkbox.toggled.connect(self._on_auto_exposure_toggled)
            self._main_layout.addWidget(self.ae_checkbox)

        # --- Create sliders for each numeric prop (excluding AE) ---
        for prop in all_props:
            # Skip non‐numeric or readonly enums, skip AE if we already did it
            if prop.id == getattr(ae_prop, "id", None):
                continue
            # Attempt to get the property's range: if it fails, skip
            try:
                r = prop_map.get_range(prop.id)
            except ic4.IC4Exception:
                continue

            # Only build for integer or float ranges
            min_val, max_val = r.min, r.max
            if min_val is None or max_val is None:
                continue
            if isinstance(min_val, (int, float)) and isinstance(max_val, (int, float)):
                # Create a QLabel + QSlider for this property
                row = QHBoxLayout()
                label = QLabel(f"{prop.name}:")
                slider = QSlider(Qt.Horizontal)
                slider.setMinimum(int(min_val))
                slider.setMaximum(int(max_val))

                # Query current value
                try:
                    cur_val = prop_map.get_value(prop.id)
                except ic4.IC4Exception as e:
                    log.warning(f"[CameraControlPanel] Could not read {prop.name}: {e}")
                    continue

                # Block signals while setting initial value
                self._block_slider_signals = True
                slider.setValue(int(cur_val))
                self._block_slider_signals = False

                # Connect change signal
                slider.valueChanged.connect(
                    lambda v, pid=prop.id, pname=prop.name: self._on_slider_changed(
                        pid, pname, v
                    )
                )

                row.addWidget(label)
                row.addWidget(slider)
                self._main_layout.addLayout(row)

                # Store reference so we can refresh later
                self.property_sliders[prop.id] = (label, slider)

        # Optionally add a "Refresh" button at the bottom
        refresh_btn = QPushButton("Refresh Properties")
        refresh_btn.clicked.connect(self.refresh_controls)
        self._main_layout.addWidget(refresh_btn)

    @pyqtSlot(bool)
    def _on_auto_exposure_toggled(self, checked: bool):
        """
        Enable or disable manual sliders based on Auto Exposure state.
        """
        if not self.grabber:
            return

        prop_map = self.grabber.device_property_map
        try:
            # Try setting the AE property
            # Use whichever PropId is supported (EXPOSURE_AUTO or GEVEXPOSUREAUTO)
            if hasattr(ic4.PropId, "EXPOSURE_AUTO"):
                prop_map.set_value(ic4.PropId.EXPOSURE_AUTO, bool(checked))
            else:
                prop_map.set_value(ic4.PropId.GevExposureAuto, bool(checked))
        except Exception as e:
            QMessageBox.warning(
                self, "Auto Exposure", f"Failed to set auto-exposure: {e}"
            )

        self._is_auto_exposure = checked
        # Enable/disable ALL sliders based on AE
        for _, slider in self.property_sliders.values():
            slider.setEnabled(not checked)

        log.info(f"[CameraControlPanel] Auto Exposure set to {checked}")
        self.auto_exposure_toggled.emit(checked)

    def _on_slider_changed(self, prop_id: ic4.PropId, prop_name: str, value: int):
        """
        Write the new slider value to the camera property.
        """
        if self._block_slider_signals:
            return
        if not self.grabber:
            return

        prop_map = self.grabber.device_property_map
        try:
            prop_map.set_value(prop_id, float(value))
            log.debug(f"[CameraControlPanel] {prop_name} set to {value}")
            self.property_changed.emit(prop_name, float(value))
        except Exception as e:
            log.error(f"[CameraControlPanel] Failed setting {prop_name}: {e}")

    def refresh_controls(self):
        """
        Re-query all property values from the camera and update sliders accordingly.
        """
        if not self.grabber:
            return

        prop_map = self.grabber.device_property_map

        # Refresh AE checkbox
        if self.ae_checkbox:
            try:
                if hasattr(ic4.PropId, "EXPOSURE_AUTO"):
                    ae_val = prop_map.get_value(ic4.PropId.EXPOSURE_AUTO)
                else:
                    ae_val = prop_map.get_value(ic4.PropId.GevExposureAuto)
                self._block_slider_signals = True
                self.ae_checkbox.setChecked(bool(ae_val))
                self._block_slider_signals = False
            except Exception as e:
                log.warning(
                    f"[CameraControlPanel] Failed re-reading auto‐exposure: {e}"
                )

        # Refresh all sliders
        for prop_id, (_, slider) in self.property_sliders.items():
            try:
                new_val = prop_map.get_value(prop_id)
                self._block_slider_signals = True
                slider.setValue(int(new_val))
                self._block_slider_signals = False
            except Exception as e:
                log.warning(f"[CameraControlPanel] Failed re-reading {prop_id}: {e}")

    def setEnabled(self, enabled: bool):
        """
        Enables/disables the entire panel. When disabling, gray out all controls.
        """
        super().setEnabled(enabled)
        if self.ae_checkbox:
            self.ae_checkbox.setEnabled(enabled)
        for _, slider in self.property_sliders.values():
            slider.setEnabled(enabled and not self._is_auto_exposure)
