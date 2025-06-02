# prim_app/ui/control_panels/camera_control_panel.py

import logging
import imagingcontrol4 as ic4
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QHBoxLayout,
    QSlider,
    QComboBox,
    QCheckBox,
)
from PyQt5.QtCore import Qt

log = logging.getLogger(__name__)


class CameraControlPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # We'll dynamically insert rows into this layout
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(6, 6, 6, 6)
        self.layout.setSpacing(10)

        # Placeholder until _on_grabber_ready is called
        self.grabber = None

    def _on_grabber_ready(self):
        """
        Called by MainWindow once the camera is open and streaming.
        self.grabber is an ic4.Grabber. We inspect grabber.device_property_map,
        then build sliders/combos/checkboxes for each property we're interested in.
        """

        if self.grabber is None:
            return

        prop_map = self.grabber.device_property_map

        # 1) First, build any enumeration‐based controls
        #    (e.g. PixelFormat, AcquisitionMode, AutoExposure, etc.)
        try:
            enum_list = prop_map.enumerations()
        except Exception as e:
            enum_list = []
            log.error(f"Could not list enumerations: {e}")

        log.info(
            f"==== Available Enumeration Properties: {[p.name for p in enum_list]}"
        )

        for enum_node in enum_list:
            name = (
                enum_node.name
            )  # e.g. "PixelFormat", "AcquisitionMode", "AutoExposure"
            try:
                # Create a simple QComboBox for this enumeration
                combo = QComboBox()
                combo.setToolTip(f"Set {name}")

                # Fill with all entries
                for entry in enum_node.entries:
                    combo.addItem(entry.name)

                # Try to set current value
                current = enum_node.value
                if current in [e.name for e in enum_node.entries]:
                    combo.setCurrentText(current)

                # When user changes index, apply it:
                combo.currentTextChanged.connect(
                    lambda v, node=enum_node: node.set_value(v)
                )

                # Put label + combo into a horizontal row
                row = QHBoxLayout()
                row.addWidget(QLabel(name))
                row.addWidget(combo)
                self.layout.addLayout(row)

            except Exception as e:
                log.error(f"Failed to build enum control for '{name}': {e}")

        # 2) Next, build integer‐based controls (sliders)
        try:
            int_list = prop_map.integers()
        except Exception as e:
            int_list = []
            log.error(f"Could not list integer properties: {e}")

        log.info(f"==== Available Integer Properties: {[p.name for p in int_list]}")

        for int_node in int_list:
            name = int_node.name  # e.g. "Gain", "Width", "Height", etc.

            # We often only want sliders for things like Gain, but skip Width/Height here
            # (since resolution is fixed at startup). Feel free to filter by name if you like.
            if name.lower() in ("width", "height"):
                continue

            try:
                # Create a QSlider spanning [min..max]
                slider = QSlider(Qt.Horizontal)
                slider.setToolTip(f"Set {name}")

                try:
                    minimum = int(int_node.minimum)
                    maximum = int(int_node.maximum)
                    increment = int(int_node.increment)
                except Exception:
                    minimum = 0
                    maximum = 100
                    increment = 1

                slider.setMinimum(minimum)
                slider.setMaximum(maximum)
                slider.setSingleStep(increment)

                # Set the slider's current position:
                current_val = int(int_node.value)
                slider.setValue(current_val)

                # When slider changes, write it back to the node
                slider.valueChanged.connect(
                    lambda v, node=int_node: node.set_value(int(v))
                )

                # Put label + slider into a horizontal row
                row = QHBoxLayout()
                row.addWidget(QLabel(name))
                row.addWidget(slider)
                self.layout.addLayout(row)

            except Exception as e:
                log.error(f"Failed to build integer slider for '{name}': {e}")

        # 3) Next, build float‐based controls (ExposureTime, etc.), if desired
        try:
            float_list = prop_map.floats()
        except Exception as e:
            float_list = []
            log.error(f"Could not list float properties: {e}")

        log.info(f"==== Available Float Properties: {[p.name for p in float_list]}")

        for float_node in float_list:
            name = float_node.name  # e.g. "ExposureTime" (in µs or ms)
            # We might skip certain floats (e.g. we already set Width/Height). Adjust as needed.
            if name.lower() in ("width", "height"):
                continue

            try:
                # Create a QSlider for the float, mapping [min..max] to an integer scale
                slider = QSlider(Qt.Horizontal)
                slider.setToolTip(f"Set {name}")

                try:
                    fmin = float(float_node.minimum)
                    fmax = float(float_node.maximum)
                    finc = float(float_node.increment)
                except Exception:
                    fmin, fmax, finc = 0.0, 100.0, 1.0

                # To display a float slider, we multiply everything by 1000 (for instance)
                # so that slider.setValue maps to an integer, then we divide by 1000 when writing.
                scale = 1_000.0
                slider.setMinimum(int(fmin * scale))
                slider.setMaximum(int(fmax * scale))
                slider.setSingleStep(int(finc * scale))

                current_f = float(float_node.value)
                slider.setValue(int(current_f * scale))

                # On slider change, set float_node.set_value(v / scale)
                def make_float_setter(node, sc):
                    return lambda v: node.set_value(float(v) / sc)

                slider.valueChanged.connect(make_float_setter(float_node, scale))

                row = QHBoxLayout()
                row.addWidget(QLabel(name))
                row.addWidget(slider)
                self.layout.addLayout(row)

            except Exception as e:
                log.error(f"Failed to build float slider for '{name}': {e}")

        # 4) Finally, build boolean‐based controls (if any), e.g. “AutoExposure”
        #    called PropBoolean under IC4. If IC4Exception is thrown, skip.
        try:
            bool_list = prop_map.booleans()
        except Exception:
            bool_list = []
            # If prop_map.booleans() doesn't exist, skip booleans.
        log.info(f"==== Available Boolean Properties: {[p.name for p in bool_list]}")

        for bool_node in bool_list:
            name = bool_node.name
            try:
                cb = QCheckBox(name)
                cb.setToolTip(f"Toggle {name}")

                # Set checked state based on current value
                try:
                    cb.setChecked(bool(bool_node.value))
                except Exception:
                    # If node.value isn't exactly True/False, skip
                    pass

                # On toggled, write back as bool
                cb.toggled.connect(
                    lambda checked, node=bool_node: node.set_value(bool(checked))
                )

                self.layout.addWidget(cb)

            except Exception as e:
                log.error(f"Failed to build boolean control for '{name}': {e}")

        # If you want fixed spacing at the bottom:
        self.layout.addStretch()
