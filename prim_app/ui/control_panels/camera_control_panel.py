import logging
import math
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget,
    QFormLayout,
    QLabel,
    QDoubleSpinBox,
    QCheckBox,
    QComboBox,
    QSlider,
    QHBoxLayout,
)

log = logging.getLogger(__name__)

PROPERTY_SPECS = [
    {
        "id_enum": "ExposureTimeAbs",
        "id_float": "ExposureTime",
        "label": "Exposure (µs)",
        "unit": "µs",
    },
    {"id_float": "Gain", "label": "Gain", "unit": ""},
    {"id_enum": "ExposureAuto", "label": "Auto Exposure", "type": "enum_bool"},
    {"id_enum": "GainAuto", "label": "Auto Gain", "type": "enum_bool"},
    {
        "id_float": "AcquisitionFrameRate",
        "label": "Frame Rate (fps)",
        "unit": "fps",
    },
    {"id_enum": "PixelFormat", "label": "Pixel Format"},
]


class CameraControlPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.grabber = None
        self.is_recording = False
        self.controls = {}

        self.layout = QFormLayout(self)
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.layout.setSpacing(6)

    def set_recording_state(self, recording: bool):
        self.is_recording = recording
        log.debug(f"CameraControlPanel: is_recording set to {self.is_recording}")

    def _set_node_value(self, node, value):
        if self.is_recording:
            log.warning("Blocked property change during recording")
            return
        try:
            node.value = value
        except Exception as e:
            ident = getattr(node, "identifier", "node")
            log.error(f"CameraControlPanel: failed to set {ident} = {value}: {e}")

    def _clear_layout(self):
        while self.layout.count():
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _on_grabber_ready(self):
        log.info("CameraControlPanel: _on_grabber_ready() called")

        if not self.grabber or not getattr(self.grabber, "is_device_open", False):
            log.error(
                "CameraControlPanel: _on_grabber_ready() called but grabber is not open."
            )
            return

        self._clear_layout()
        self.controls.clear()

        for spec in PROPERTY_SPECS:
            enum_node = None
            if spec.get("id_enum"):
                try:
                    enum_node = self.grabber.device_property_map.find_enumeration(
                        spec["id_enum"]
                    )
                except Exception:
                    enum_node = None

            if enum_node:
                if spec.get("type") == "enum_bool":
                    chk = QCheckBox(spec["label"])
                    chk.setChecked(enum_node.value in ("Continuous", "On", True))
                    chk.stateChanged.connect(
                        lambda st, n=enum_node: self._set_node_value(
                            n, "Continuous" if st == Qt.Checked else "Off"
                        )
                    )
                    self.layout.addRow(chk)
                    self.controls[spec.get("id_enum")] = chk
                else:
                    combo = QComboBox()
                    for entry in enum_node.entries:
                        combo.addItem(entry.name)
                    combo.setCurrentText(enum_node.value)
                    combo.currentTextChanged.connect(
                        lambda v, n=enum_node: self._set_node_value(n, v)
                    )
                    self.layout.addRow(QLabel(spec["label"]), combo)
                    self.controls[spec.get("id_enum")] = combo
                continue

            float_node = None
            if spec.get("id_float"):
                try:
                    float_node = self.grabber.device_property_map.find_float(
                        spec["id_float"]
                    )
                except Exception:
                    float_node = None
            if not float_node:
                log.warning(
                    f"CameraControlPanel: Property {spec.get('id_float')} not found."
                )
                continue

            lo, hi = float_node.minimum, float_node.maximum

            try:
                incr = float_node.increment
            except Exception:
                incr = 0

            step = incr if incr and incr > 0 else (hi - lo) / 100.0
            cur_val = float_node.value

            spin = QDoubleSpinBox()
            spin.setSuffix(f" {spec.get('unit', '')}")
            spin.setRange(lo, hi)
            spin.setSingleStep(step)
            if step < 1.0:
                dec = max(0, -int(math.floor(math.log10(step))))
            else:
                dec = 0
            spin.setDecimals(min(dec, 6))
            spin.setValue(cur_val)

            slider = QSlider(Qt.Horizontal)
            scale = 10 ** dec
            slider.setRange(int(lo * scale), int(hi * scale))
            slider.setSingleStep(max(1, int(step * scale)))
            slider.setValue(int(cur_val * scale))

            spin.valueChanged.connect(
                lambda v, n=float_node, s=slider, sc=scale: (
                    self._set_node_value(n, float(v)),
                    s.setValue(int(v * sc)),
                )
            )
            slider.valueChanged.connect(
                lambda iv, sp=spin, sc=scale: sp.setValue(iv / sc)
            )

            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.addWidget(slider)
            hl.addWidget(spin)
            self.layout.addRow(QLabel(spec["label"]), row)
            self.controls[spec.get("id_float")] = (spin, slider)

