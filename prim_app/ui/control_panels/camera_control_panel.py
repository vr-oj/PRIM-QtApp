# prim_app/ui/control_panels/camera_control_panel.py

import logging
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QSlider, QHBoxLayout, QComboBox
from PyQt5.QtCore import Qt, pyqtSlot

log = logging.getLogger(__name__)


class CameraControlPanel(QWidget):
    """
    A panel of dynamic camera controls (gain, exposure, etc.) once the grabber is open.
    MainWindow will do:
        camera_control_panel.grabber = <ic4.Grabber>
        camera_control_panel._on_grabber_ready()
    at which point we can query self.grabber.device_property_map to populate sliders.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.grabber = None  # Will be set by MainWindow after camera opens

        # A vertical layout to hold dynamic controls
        self.setLayout(QVBoxLayout())
        self._header = QLabel("Camera Controls (not connected)")
        self.layout().addWidget(self._header)

        # Placeholder containers; you can replace with your actual control widgets
        self._sliders_container = QWidget()
        self._sliders_container.setLayout(QVBoxLayout())
        self.layout().addWidget(self._sliders_container)

    @pyqtSlot()
    def _on_grabber_ready(self):
        """
        Called by MainWindow right after the grabber is opened and streaming.
        Now self.grabber is valid, so we can query device_property_map.
        """
        if self.grabber is None:
            log.error("CameraControlPanel: No grabber was provided at _on_grabber_ready().")
            return

        # Clear any existing controls
        for i in reversed(range(self._sliders_container.layout().count())):
            widget_to_remove = self._sliders_container.layout().itemAt(i).widget()
            if widget_to_remove is not None:
                widget_to_remove.setParent(None)

        # Update header
        self._header.setText("Camera Controls (connected)")

        prop_map = self.grabber.device_property_map

        # Log (for debugging) some enumeration keys available
        try:
            all_enums = [e.name for e in prop_map.all if hasattr(e, "name")]
            log.info(f"====== Available Enumeration Properties: {all_enums}")
        except Exception:
            log.exception("Could not list enumeration properties.")

        # EXAMPLE: If you want to expose “Gain” (assuming there’s a PropFloat named “Gain”):
        try:
            gain_prop = prop_map.find_float("Gain")
            if gain_prop is not None:
                # Create a slider for Gain
                gain_slider = QSlider(Qt.Horizontal)
                gain_slider.setMinimum(int(gain_prop.minimum))
                gain_slider.setMaximum(int(gain_prop.maximum))
                gain_slider.setValue(int(gain_prop.value))
                gain_slider.setSingleStep(int(gain_prop.increment))
                gain_slider.setToolTip(f"Gain: {gain_prop.value:.2f}")

                def on_gain_change(val: int):
                    try:
                        gain_prop.value = float(val)
                        gain_slider.setToolTip(f"Gain: {gain_prop.value:.2f}")
                    except Exception:
                        pass

                gain_slider.valueChanged.connect(on_gain_change)

                # Label + slider horizontally
                container = QWidget()
                row = QHBoxLayout(container)
                row.addWidget(QLabel("Gain"))
                row.addWidget(gain_slider)
                self._sliders_container.layout().addWidget(container)
        except Exception:
            log.exception("Failed to build Gain control.")

        # EXAMPLE: If you want to expose “ExposureTime” (PropFloat named “ExposureTime”):
        try:
            exp_prop = prop_map.find_float("ExposureTime")
            if exp_prop is not None:
                exp_slider = QSlider(Qt.Horizontal)
                exp_slider.setMinimum(int(exp_prop.minimum))
                exp_slider.setMaximum(int(exp_prop.maximum))
                exp_slider.setValue(int(exp_prop.value))
                exp_slider.setSingleStep(int(exp_prop.increment))
                exp_slider.setToolTip(f"ExposureTime: {exp_prop.value:.2f}")

                def on_exposure_change(val: int):
                    try:
                        exp_prop.value = float(val)
                        exp_slider.setToolTip(f"ExposureTime: {exp_prop.value:.2f}")
                    except Exception:
                        pass

                exp_slider.valueChanged.connect(on_exposure_change)

                container = QWidget()
                row = QHBoxLayout(container)
                row.addWidget(QLabel("Exposure"))
                row.addWidget(exp_slider)
                self._sliders_container.layout().addWidget(container)
        except Exception:
            log.exception("Failed to build Exposure control.")

        # If you want to expose an enumeration (e.g. “PixelFormat”), you could do something like:
        try:
            pf_enum = prop_map.find_enumeration("PixelFormat")
            if pf_enum is not None:
                pf_combo = QComboBox()
                for entry in pf_enum.entries:
                    pf_combo.addItem(entry.name)
                # Set current index
                current_index = [i for i, e in enumerate(pf_enum.entries) if e.name == pf_enum.value]
                if current_index:
                    pf_combo.setCurrentIndex(current_index[0])

                def on_pf_change(idx: int):
                    try:
                        new_name = pf_enum.entries[idx].name
                        pf_enum.value = new_name
                    except Exception:
                        pass

                pf_combo.currentIndexChanged.connect(on_pf_change)

                container = QWidget()
                row = QHBoxLayout(container)
                row.addWidget(QLabel("PixelFormat"))
                row.addWidget(pf_combo)
                self._sliders_container.layout().addWidget(container)
        except Exception:
            log.exception("Failed to build PixelFormat control.")

        # … add more controls as needed …