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

# Map auto properties to the float property they control
AUTO_MAP = {"ExposureAuto": "ExposureTime", "GainAuto": "Gain"}


class CameraControlPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.grabber = None
        self.is_recording = False
        self.controls = {}
        self.blocks = {}
        self.scales = {}
        self.nodes = {}

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

    def update_property(self, ident: str, value):
        ctrl = self.controls.get(ident)
        if ctrl is None:
            return
        if isinstance(ctrl, tuple):
            spin, slider = ctrl
            block = self.blocks.get(ident, {"val": False})
            scale = self.scales.get(ident, 1)
            self.blocks[ident] = block
            block["val"] = True
            try:
                spin.setValue(float(value))
                slider.setValue(int(float(value) * scale))
            finally:
                block["val"] = False
        elif isinstance(ctrl, QCheckBox):
            checked = value in ("Continuous", "On", True, 1, "True")
            ctrl.blockSignals(True)
            ctrl.setChecked(checked)
            ctrl.blockSignals(False)
            float_name = AUTO_MAP.get(ident)
            if float_name and float_name in self.controls:
                sp, sl = self.controls[float_name]
                sp.setEnabled(not checked)
                sl.setEnabled(not checked)

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

                    def _auto_changed(st, n=enum_node, ident=spec.get("id_enum")):
                        self._set_node_value(n, "Continuous" if st == Qt.Checked else "Off")
                        float_name = AUTO_MAP.get(ident)
                        if float_name and float_name in self.controls:
                            sp, sl = self.controls[float_name]
                            enabled = st != Qt.Checked
                            sp.setEnabled(enabled)
                            sl.setEnabled(enabled)

                    chk.stateChanged.connect(_auto_changed)
                    self.layout.addRow(chk)
                    self.controls[spec.get("id_enum")] = chk
                    self.nodes[spec.get("id_enum")] = enum_node
                else:
                    combo = QComboBox()
                    for entry in enum_node.entries:
                        combo.addItem(entry.name)
                    combo.setCurrentText(enum_node.value)

                    def _combo_changed(v, n=enum_node):
                        self._set_node_value(n, v)

                    combo.currentTextChanged.connect(_combo_changed)
                    self.layout.addRow(QLabel(spec["label"]), combo)
                    self.controls[spec.get("id_enum")] = combo
                    self.nodes[spec.get("id_enum")] = enum_node
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

            block = {"val": False}

            def _spin_changed(v, n=float_node, s=slider, sc=scale, b=block):
                if b["val"]:
                    return
                b["val"] = True
                self._set_node_value(n, float(v))
                s.setValue(int(v * sc))
                b["val"] = False

            def _slider_changed(iv, sp=spin, sc=scale, n=float_node, b=block):
                if b["val"]:
                    return
                b["val"] = True
                val = iv / sc
                sp.setValue(val)
                self._set_node_value(n, float(val))
                b["val"] = False

            spin.valueChanged.connect(_spin_changed)
            slider.valueChanged.connect(_slider_changed)

            self.blocks[spec.get("id_float")] = block
            self.scales[spec.get("id_float")] = scale
            self.nodes[spec.get("id_float")] = float_node

            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.addWidget(slider)
            hl.addWidget(spin)
            self.layout.addRow(QLabel(spec["label"]), row)
            self.controls[spec.get("id_float")] = (spin, slider)

        # Disable manual controls if auto is already enabled
        for auto_ident, float_ident in AUTO_MAP.items():
            chk = self.controls.get(auto_ident)
            if isinstance(chk, QCheckBox) and chk.isChecked():
                ctrl = self.controls.get(float_ident)
                if ctrl:
                    ctrl[0].setEnabled(False)
                    ctrl[1].setEnabled(False)

