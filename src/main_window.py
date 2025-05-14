import sys
import os
import logging

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel,
    QSplitter, QHBoxLayout, QVBoxLayout, QToolBar, QAction,
    QComboBox, QFileDialog, QDockWidget, QTextEdit,
    QLineEdit, QPushButton, QStatusBar, QDialog,
    QFormLayout, QDialogButtonBox, QSpinBox, QDoubleSpinBox,
    QSizePolicy, QCheckBox, QGroupBox, QSlider, QStyleFactory
)
from PyQt5.QtCore import Qt, QTimer, QSize, pyqtSignal
from PyQt5.QtGui import QIcon, QFont, QImage, QPixmap, QPalette, QColor

from threads.qtcamera_widget import QtCameraWidget
from threads.serial_thread import SerialThread
from recording import TrialRecorder
from utils import list_serial_ports, list_cameras

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# ─── Logging ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s"
)
log = logging.getLogger(__name__)


class TopControlPanel(QWidget):
    """Flat panel with Camera / PRIM box / Plot controls."""
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(20)

        # — Camera controls —
        cam_box = QGroupBox("Camera")
        cam_box.setFlat(True)
        cam_layout = QFormLayout(cam_box)
        self.cam_selector = QComboBox()
        for idx in list_cameras(4):
            self.cam_selector.addItem(f"Camera {idx}", idx)
        cam_layout.addRow("Device:", self.cam_selector)

        self.res_selector = QComboBox()
        cam_layout.addRow("Resolution:", self.res_selector)

        self.gain_slider = QSlider(Qt.Horizontal)
        cam_layout.addRow("Gain:", self.gain_slider)

        self.bright_slider = QSlider(Qt.Horizontal)
        cam_layout.addRow("Brightness:", self.bright_slider)

        self.contrast_slider = QSlider(Qt.Horizontal)
        cam_layout.addRow("Contrast:", self.contrast_slider)

        layout.addWidget(cam_box, 1)

        # — PRIM box controls —
        box_box = QGroupBox("PRIM Box")
        box_box.setFlat(True)
        box_layout = QFormLayout(box_box)
        self.pressure_spin = QDoubleSpinBox()
        self.pressure_spin.setRange(0, 300)
        self.pressure_spin.setSuffix(" mmHg")
        box_layout.addRow("Setpoint:", self.pressure_spin)

        adj_row = QWidget()
        rh = QHBoxLayout(adj_row)
        rh.setContentsMargins(0,0,0,0)
        self.btn_decr = QPushButton("–")
        self.btn_incr = QPushButton("+")
        rh.addWidget(self.btn_decr)
        rh.addWidget(self.btn_incr)
        box_layout.addRow("Adjust:", adj_row)

        layout.addWidget(box_box, 1)

        # — Plot controls —
        plot_box = QGroupBox("Plot")
        plot_box.setFlat(True)
        plot_layout = QFormLayout(plot_box)
        self.auto_x_cb = QCheckBox()
        plot_layout.addRow("Auto‑scale X:", self.auto_x_cb)
        self.auto_y_cb = QCheckBox()
        plot_layout.addRow("Auto‑scale Y:", self.auto_y_cb)
        self.reset_btn = QPushButton("↺ Reset Zoom")
        plot_layout.addRow(self.reset_btn)

        layout.addWidget(plot_box, 1)


class PressurePlotWidget(QWidget):
    """Matplotlib-based pressure vs time plot."""
    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0,0,0,0)
        self.fig = Figure(figsize=(4,3))
        self.ax = self.fig.add_subplot(111)
        self.line, = self.ax.plot([], [], '-', lw=2)
        self.canvas = FigureCanvas(self.fig)
        v.addWidget(self.canvas)

        self.times = []
        self.pressures = []

    def update(self, t, p, auto_x, auto_y, xlim, ylim):
        self.times.append(t)
        self.pressures.append(p)
        self.line.set_data(self.times, self.pressures)

        if auto_x:
            self.ax.set_xlim(0, max(self.times)+1)
        elif xlim:
            self.ax.set_xlim(*xlim)

        if auto_y:
            lo, hi = min(self.pressures), max(self.pressures)
            self.ax.set_ylim(lo-1, hi+1)
        elif ylim:
            self.ax.set_ylim(*ylim)

        self.canvas.draw()


class MainWindow(QMainWindow):
    frame_ready = pyqtSignal(QImage, object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PRIM Live View")
        self._base = os.path.dirname(__file__)

        # threads & recorders
        self._serial_thread = None
        self.trial_recorder = None

        # plot state
        self.plot_xlim = (0, None)
        self.plot_ylim = (0, 30)

        # build up UI
        self._build_menu()
        self._build_toolbar()
        self._build_central()
        self._build_console()
        self._build_statusbar()

        # center‐split proportions: 50/50
        self.showMaximized()
        QTimer.singleShot(0, self._equalize_splitter)

    def _build_menu(self):
        mb = self.menuBar()
        # File
        file_menu = mb.addMenu("File")
        file_menu.addAction("Save Trial…", self._on_save)
        file_menu.addAction("Export Data…", self._on_export)
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)

        # Acquisition
        acq_menu = mb.addMenu("Acquisition")
        acq_menu.addAction("Start Trial", self._start_trial, Qt.CTRL + Qt.Key_R)
        acq_menu.addAction("Stop Trial", self._stop_trial, Qt.CTRL + Qt.Key_T)

        # Stubs
        mb.addMenu("ROIs")
        mb.addMenu("Plot")
        help_menu = mb.addMenu("Help")
        help_menu.addAction("About", self._on_about)

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setIconSize(QSize(24,24))
        self.addToolBar(tb)

        icon_dir = os.path.join(self._base, "icons")

        # Connect / Disconnect
        plug = QIcon(os.path.join(icon_dir,"plug.svg"))
        self.act_connect = QAction(plug, "", self, triggered=self._toggle_serial)
        tb.addAction(self.act_connect)

        # Record
        rec = QIcon(os.path.join(icon_dir,"record.svg"))
        self.act_record = QAction(rec, "", self, enabled=False, triggered=self._start_trial)
        tb.addAction(self.act_record)

        stop = QIcon(os.path.join(icon_dir,"stop.svg"))
        self.act_stop = QAction(stop, "", self, enabled=False, triggered=self._stop_trial)
        tb.addAction(self.act_stop)

        tb.addSeparator()

        # Serial port combobox
        self.port_combo = QComboBox()
        self.port_combo.addItem("🔧 Simulated Data", None)
        for port, desc in list_serial_ports():
            self.port_combo.addItem(f"{port} ({desc})", port)
        tb.addWidget(self.port_combo)

    def _build_central(self):
        cw = QWidget()
        v = QVBoxLayout(cw)
        v.setContentsMargins(0,0,0,0)
        v.setSpacing(0)

        # top controls
        self.top_ctrl = TopControlPanel()
        v.addWidget(self.top_ctrl)

        # center splitter
        self.splitter = QSplitter(Qt.Horizontal)
        # left: camera
        self.qt_cam = QtCameraWidget(self)
        self.qt_cam.frame_ready.connect(self._on_frame)
        self.splitter.addWidget(self.qt_cam)
        # right: plot
        self.plot_w = PressurePlotWidget()
        self.splitter.addWidget(self.plot_w)

        v.addWidget(self.splitter, 1)
        self.setCentralWidget(cw)

    def _build_console(self):
        dock = QDockWidget("Console", self)
        dock.setAllowedAreas(Qt.BottomDockWidgetArea)
        dock.setFixedHeight(120)
        cw = QWidget()
        vv = QVBoxLayout(cw)
        self.console_out = QTextEdit()
        self.console_out.setReadOnly(True)
        row = QWidget()
        hh = QHBoxLayout(row)
        self.console_in = QLineEdit()
        send = QPushButton("Send")
        send.clicked.connect(self._on_console_send)
        hh.addWidget(self.console_in)
        hh.addWidget(send)
        vv.addWidget(self.console_out)
        vv.addWidget(row)
        dock.setWidget(cw)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)

    def _build_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.time_lbl = QLabel("Elapsed: 0s")
        sb.addPermanentWidget(self.time_lbl)
        self._elapsed = 0
        timer = QTimer(self, interval=1000, timeout=self._tick)
        timer.start()

    def _equalize_splitter(self):
        total = self.splitter.width()
        self.splitter.setSizes([total//2, total//2])

    # ─── Slots & plumbing ────────────────────────────────────────

    def _on_frame(self, img: QImage, bgr):
        # video preview only
        # (QtCameraWidget already shows it)
        # record if active
        if self.trial_recorder and bgr is not None:
            self.trial_recorder.write_frame(bgr)

    def _toggle_serial(self):
        if not self._serial_thread:
            port = self.port_combo.currentData()
            self._serial_thread = SerialThread(port=port, baud=115200)
            self._serial_thread.data_ready.connect(self._on_data)
            self._serial_thread.start()
            self.act_connect.setIcon(QIcon(os.path.join(self._base,"icons","plug-disconnect.svg")))
            self.act_record.setEnabled(True)
        else:
            self._serial_thread.stop()
            self._serial_thread = None
            self.act_connect.setIcon(QIcon(os.path.join(self._base,"icons","plug.svg")))
            self.act_record.setEnabled(False)

    def _start_trial(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Trial As…", "", "")
        if not path:
            return
        self.trial_recorder = TrialRecorder(path, fps=30, frame_size=(640,480))
        self.act_record.setEnabled(False)
        self.act_stop.setEnabled(True)

    def _stop_trial(self):
        if self.trial_recorder:
            self.trial_recorder.stop()
            self.trial_recorder = None
        self.act_record.setEnabled(True)
        self.act_stop.setEnabled(False)

    def _on_data(self, idx, t, p):
        auto_x = self.top_ctrl.auto_x_cb.isChecked()
        auto_y = self.top_ctrl.auto_y_cb.isChecked()
        self.plot_w.update(t, p, auto_x, auto_y, self.plot_xlim, self.plot_ylim)
        self.console_out.append(f"{idx}, {t:.2f}, {p:.2f}")

    def _on_console_send(self):
        txt = self.console_in.text().strip()
        if txt and self._serial_thread:
            self._serial_thread.ser.write(txt.encode()+b"\n")
            self.console_in.clear()

    def _tick(self):
        self._elapsed += 1
        self.time_lbl.setText(f"Elapsed: {self._elapsed}s")

    def _on_save(self):
        # stub for File→Save Trial…
        pass

    def _on_export(self):
        # stub for File→Export Data…
        pass

    def _on_about(self):
        # stub for Help→About…
        pass

    def closeEvent(self, ev):
        if self._serial_thread:
            self._serial_thread.stop()
        super().closeEvent(ev)


def main():
    app = QApplication(sys.argv)
    # apply Fusion light palette
    app.setStyle(QStyleFactory.create("Fusion"))
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(250,250,250))
    pal.setColor(QPalette.WindowText, Qt.black)
    pal.setColor(QPalette.Base, QColor(240,240,240))
    pal.setColor(QPalette.AlternateBase, QColor(250,250,250))
    pal.setColor(QPalette.ToolTipBase, Qt.black)
    pal.setColor(QPalette.ToolTipText, Qt.black)
    pal.setColor(QPalette.Text, Qt.black)
    pal.setColor(QPalette.Button, QColor(245,245,245))
    pal.setColor(QPalette.ButtonText, Qt.black)
    pal.setColor(QPalette.Highlight, QColor(51,153,255))
    pal.setColor(QPalette.HighlightedText, Qt.white)
    app.setPalette(pal)

    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
