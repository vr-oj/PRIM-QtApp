import logging
from PyQt5.QtWidgets import (
    QGroupBox,
    QWidget,
    QTabWidget,
    QFormLayout,
    QScrollArea,
    QLabel,
    QComboBox,
    QDoubleSpinBox,
    QCheckBox,
    QPushButton,
    QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot

# Import your CameraController that wraps Harvester/GenTL logic
from camera_controller import CameraController

log = logging.getLogger(__name__)


class CameraControlPanel(QGroupBox):
    """
    Dynamic control panel that exposes all camera parameters available
    via the provided CameraController instance.
    """

    parameter_changed = pyqtSignal(str, object)

    def __init__(self, controller: CameraController, parent=None):
        super().__init__("Camera Controls", parent)
        self.controller = controller

        # Main layout: a single tab widget
        self.tabs = QTabWidget()
        main_layout = QFormLayout(self)
        main_layout.addRow(self.tabs)

        # Create a scrollable parameters panel
        params_widget = QWidget()
        params_layout = QFormLayout(params_widget)
        params_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.controls = {}
        # Build controls for each node in the camera
        for name, node in sorted(self.controller.node_map.items()):
            widget = self._create_widget_for_node(name, node)
            if widget:
                params_layout.addRow(QLabel(name), widget)
                self.controls[name] = widget

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(params_widget)
        self.tabs.addTab(scroll, "Parameters")

        # Hook UI events back to controller
        self.parameter_changed.connect(self._on_parameter_changed)

        # If CameraController can emit when capabilities update, hook that
        if hasattr(self.controller, "capabilities_changed"):
            self.controller.capabilities_changed.connect(self._refresh_controls)

    def _create_widget_for_node(self, name, node):
        """
        Factory: return an appropriate widget depending on node type.
        """
        # Enumeration node → combo box
        if hasattr(node, "symbolics"):
            combo = QComboBox()
            for opt in node.symbolics:
                combo.addItem(opt)
            try:
                combo.setCurrentText(str(node.value))
            except Exception:
                pass
            combo.currentTextChanged.connect(
                lambda v, n=name: self.parameter_changed.emit(n, v)
            )
            return combo

        # Boolean node → check box
        if node.__class__.__name__ == "IBoolean":
            cb = QCheckBox()
            try:
                cb.setChecked(bool(node.value))
            except Exception:
                pass
            cb.toggled.connect(lambda v, n=name: self.parameter_changed.emit(n, v))
            return cb

        # Numeric node (IInteger or IFloat) → double spin box
        if node.__class__.__name__ in ("IInteger", "IFloat"):
            spin = QDoubleSpinBox()
            try:
                spin.setRange(node.min, node.max)
                spin.setSingleStep(getattr(node, "increment", 1))
                spin.setValue(node.value)
            except Exception:
                pass
            spin.valueChanged.connect(
                lambda v, n=name: self.parameter_changed.emit(n, v)
            )
            return spin

        # Command node → button
        if node.__class__.__name__ == "ICommand":
            btn = QPushButton("Execute")
            btn.clicked.connect(lambda _, n=name: self.parameter_changed.emit(n, None))
            return btn

        # Other node types not supported by UI
        return None

    @pyqtSlot(str, object)
    def _on_parameter_changed(self, name, value):
        """
        Slot: send UI-driven changes to the camera controller.
        """
        try:
            self.controller.set_node_value(name, value)
            log.info(f"Set {name} to {value}")
        except Exception as e:
            log.error(f"Failed to set {name} to {value}: {e}")

    @pyqtSlot()
    def _refresh_controls(self):
        """
        Refresh widget values after capabilities changed in controller.
        """
        for name, widget in self.controls.items():
            node = self.controller.node_map.get(name)
            if not node:
                continue
            try:
                if hasattr(node, "value"):
                    if isinstance(widget, QComboBox):
                        widget.setCurrentText(str(node.value))
                    elif isinstance(widget, QCheckBox):
                        widget.setChecked(bool(node.value))
                    elif isinstance(widget, QDoubleSpinBox):
                        widget.setValue(node.value)
            except Exception:
                pass
