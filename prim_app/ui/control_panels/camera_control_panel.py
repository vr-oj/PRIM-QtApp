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
        "label": "Exposure",
        "unit": "ms",
        "display_scale": 0.001,  # convert µs -> ms
        "log_slider": True,
    },
    {"id_float": "Gain", "label": "Gain", "unit": ""},
    {"id_enum": "ExposureAuto", "label": "Auto Exposure", "type": "enum_bool", "auto_target": "ExposureTime"},
    {"id_enum": "GainAuto", "label": "Auto Gain", "type": "enum_bool", "auto_target": "Gain"},
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

    # ------------------------------------------------------------------
    # Helper methods
    def _slider_to_value(self, sval: int, lo: float, hi: float, log=False) -> float:
        pos = max(0.0, min(1.0, sval / 100.0))
        if log and lo > 0 and hi > lo:
            return lo * (hi / lo) ** pos
        return lo + pos * (hi - lo)

    def _value_to_slider(self, val: float, lo: float, hi: float, log=False) -> int:
        if log and val > 0 and lo > 0 and hi > lo:
            pos = math.log(val / lo) / math.log(hi / lo)
        else:
            pos = (val - lo) / (hi - lo) if hi != lo else 0
        pos = max(0.0, min(1.0, pos))
        return int(pos * 100)

    def _toggle_float_controls(self, float_id: str, enabled: bool) -> None:
        ctrl = self.controls.get(float_id)
        if ctrl and isinstance(ctrl, tuple):
            spin, slider = ctrl
            spin.setEnabled(enabled)
            slider.setEnabled(enabled)

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
                    tgt = spec.get("auto_target")
                    if tgt:
                        chk.stateChanged.connect(
                            lambda st, fid=tgt: self._toggle_float_controls(fid, st != Qt.Checked)
                        )
                        self._toggle_float_controls(tgt, chk.isChecked() == False)
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

            disp_scale = spec.get("display_scale", 1.0)
            log_slider = spec.get("log_slider", False)

            spin = QDoubleSpinBox()
            spin.setSuffix(f" {spec.get('unit', '')}")
            spin.setRange(lo * disp_scale, hi * disp_scale)
            spin.setSingleStep(step * disp_scale)
            if step < 1.0:
                dec = max(0, -int(math.floor(math.log10(step))))
            else:
                dec = 0
            spin.setDecimals(min(dec, 6))
            spin.setValue(cur_val * disp_scale)

            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(self._value_to_slider(cur_val, lo, hi, log_slider))

            spin.valueChanged.connect(
                lambda v, s=slider, lo=lo, hi=hi, log=log_slider, sc=disp_scale: s.setValue(
                    self._value_to_slider(v / sc, lo, hi, log)
                )
            )
            spin.editingFinished.connect(
                lambda n=float_node, sp=spin, sc=disp_scale: self._set_node_value(
                    n, sp.value() / sc
                )
            )
            slider.valueChanged.connect(
                lambda iv, sp=spin, lo=lo, hi=hi, log=log_slider, sc=disp_scale: sp.setValue(
                    self._slider_to_value(iv, lo, hi, log) * sc
                )
            )
            slider.sliderReleased.connect(
                lambda n=float_node, sl=slider, lo=lo, hi=hi, log=log_slider: self._set_node_value(
                    n, self._slider_to_value(sl.value(), lo, hi, log)
                )
            )

            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.addWidget(slider)
            hl.addWidget(spin)
            self.layout.addRow(QLabel(spec["label"]), row)
            self.controls[spec.get("id_float")] = (spin, slider)

