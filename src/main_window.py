import sys, cv2

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel,
    QSplitter, QHBoxLayout, QVBoxLayout, QToolBar, QAction,
    QComboBox, QFileDialog, QDockWidget, QTextEdit,
    QLineEdit, QPushButton, QStatusBar, QDialog,
    QFormLayout, QDialogButtonBox, QSpinBox, QDoubleSpinBox,
    QSizePolicy, QCheckBox
)
from PyQt5.QtGui import QImage, QPixmap, QIcon, QFont
from PyQt5.QtCore import Qt, QTimer, QSize
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from threads.video_thread import VideoThread
from threads.serial_thread import SerialThread
from recording import TrialRecorder
from utils import list_serial_ports, timestamped_filename, list_cameras

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PRIM Live View")

        # Buffers for plotting
        self.frames    = []
        self.times     = []
        self.pressures = []
        self._t0       = None

        # Plot axis control
        self.plot_auto_x = True
        self.plot_auto_y = False
        self.plot_xlim   = (0, None)
        self.plot_ylim   = (0, 30)

        # Threads and state
        self._serial_thread = None
        self.trial_recorder = None
        self.latest_frame   = None

        # **NEW** store the full original pixmap for resizing
        self._last_pixmap   = None

        self._build_ui()
        self._start_video_thread()
        self.showMaximized()

    def _build_ui(self):
        # ─── Menu bar ─────────────────────────────────────────────────────
        mb = self.menuBar()
        cam_menu = mb.addMenu("Camera")
        cam_settings = QAction("Settings...", self)
        cam_settings.triggered.connect(self._show_camera_settings)
        cam_menu.addAction(cam_settings)
        plot_menu = mb.addMenu("Plot")
        plot_settings = QAction("Axis Settings...", self)
        plot_settings.triggered.connect(self._show_plot_settings)
        plot_menu.addAction(plot_settings)

        # ─── Plot setup ────────────────────────────────────────────────────
        self.fig = Figure(figsize=(5, 4))
        self.ax  = self.fig.add_subplot(111)
        self.line, = self.ax.plot([], [], '-')
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setMinimumWidth(200)

        # ─── Central splitter ───────────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)

        # Video display
        self.video_label = QLabel()
        self.video_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_label.setScaledContents(False)     # important!
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumWidth(200)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.video_label)
        self.splitter.addWidget(self.canvas)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)

        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.splitter)

        # ─── Console dock ──────────────────────────────────────────────────
        self.console_dock = QDockWidget("Console", self)
        self.console_dock.setAllowedAreas(Qt.BottomDockWidgetArea)
        cw = QWidget()
        cl = QVBoxLayout(cw)
        self.console_output = QTextEdit()
        self.console_output.setReadOnly(True)
        il = QHBoxLayout()
        self.console_input = QLineEdit()
        btn = QPushButton("Send")
        btn.clicked.connect(self._on_console_send)
        il.addWidget(self.console_input)
        il.addWidget(btn)
        cl.addWidget(self.console_output)
        cl.addLayout(il)
        self.console_dock.setWidget(cw)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.console_dock)
        self.console_dock.setFixedHeight(150)

        # ─── Toolbar ────────────────────────────────────────────────────────
        tb = QToolBar("Main Toolbar")
        self.addToolBar(tb)
        tb.setIconSize(QSize(28, 28))
        tb.setToolButtonStyle(Qt.ToolButtonIconOnly)
        tb.setFont(QFont("Segoe UI", 10))

        # Serial port dropdown
        self.port_combo = QComboBox()
        self.port_combo.addItem("🔧 Simulated Data", None)
        for port, desc in list_serial_ports():
            self.port_combo.addItem(f"{port} ({desc})", port)
        tb.addWidget(self.port_combo)

        # Connect / Init / Start / Stop
        self.actConnect = QAction(QIcon("icons/plug.svg"), "", self)
        self.actConnect.setToolTip("Connect (Ctrl+K)")
        self.actConnect.setShortcut("Ctrl+K")
        tb.addAction(self.actConnect)

        self.actInit = QAction(QIcon("icons/sync.svg"), "", self)
        self.actInit.setEnabled(False)
        self.actInit.setToolTip("Re‑Sync (Ctrl+I)")
        self.actInit.setShortcut("Ctrl+I")
        tb.addAction(self.actInit)

        self.actStart = QAction(QIcon("icons/record.svg"), "", self)
        self.actStart.setEnabled(False)
        self.actStart.setToolTip("Start Trial (Ctrl+R)")
        self.actStart.setShortcut("Ctrl+R")
        tb.addAction(self.actStart)

        self.actStop = QAction(QIcon("icons/stop.svg"), "", self)
        self.actStop.setEnabled(False)
        self.actStop.setToolTip("Stop Trial (Ctrl+T)")
        self.actStop.setShortcut("Ctrl+T")
        tb.addAction(self.actStop)

        tb.addSeparator()

        # Pump On / Off
        self.actPumpOn = QAction(QIcon("icons/pump-on.svg"), "", self)
        self.actPumpOn.setToolTip("Pump On (Ctrl+P)")
        self.actPumpOn.setShortcut("Ctrl+P")
        tb.addAction(self.actPumpOn)

        self.actPumpOff = QAction(QIcon("icons/pump-off.svg"), "", self)
        self.actPumpOff.setToolTip("Pump Off (Ctrl+O)")
        self.actPumpOff.setShortcut("Ctrl+O")
        tb.addAction(self.actPumpOff)

        tb.addSeparator()

        # Sync indicator
        self.sync_icon = QLabel("Sync: ❓")
        tb.addWidget(self.sync_icon)

        # New Session
        self.actNewSession = QAction(QIcon("icons/file-plus.svg"), "", self)
        self.actNewSession.setToolTip("New Session (Ctrl+N)")
        self.actNewSession.setShortcut("Ctrl+N")
        tb.addAction(self.actNewSession)

        # Camera selector dropdown
        self.cam_combo = QComboBox()
        for i in list_cameras(4):
            self.cam_combo.addItem(f"Camera {i}", i)
        if self.cam_combo.count() == 0:
            self.cam_combo.addItem("No cameras found", None)
        tb.addWidget(self.cam_combo)

        # ─── Status bar & timer ────────────────────────────────────────────
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self._elapsed = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_status)
        self._timer.start(1000)

        # ─── Hook up actions ───────────────────────────────────────────────
        self.actConnect .triggered.connect(self._toggle_serial)
        self.actInit    .triggered.connect(self._send_init)
        self.actStart   .triggered.connect(self._start_trial)
        self.actStop    .triggered.connect(self._stop_trial)
        self.actPumpOn  .triggered.connect(lambda: self._send_serial_cmd(b"PUMP_ON\n"))
        self.actPumpOff .triggered.connect(lambda: self._send_serial_cmd(b"PUMP_OFF\n"))
        self.actNewSession.triggered.connect(self._show_metadata_dialog)
    
    def showEvent(self, event):
        super().showEvent(event)
        total = self.centralWidget().width()
        self.splitter.setSizes([total//2, total-total//2])
        # only run once
        self.showEvent = QMainWindow.showEvent


    def resizeEvent(self, event):
        # whenever the window (or splitter) moves,
        # re‑scale to the new label size
        super().resizeEvent(event)
        self._update_video_label()


    def _update_video_label(self):
        """Scale the last pixmap to *fit* the QLabel in both dims."""
        if not self._last_pixmap:
            return
        scaled = self._last_pixmap.scaled(
            self.video_label.size(),      # target rect
            Qt.KeepAspectRatio,           # preserve entire image
            Qt.SmoothTransformation
        )
        self.video_label.setPixmap(scaled)

    def _start_video_thread(self):
        idx = self.cam_combo.currentData() or 0
        self.video_thread = VideoThread(camera_index=idx)
        self.video_thread.frame_ready.connect(self._on_frame)
        self.video_thread.start()

    def _on_frame(self, img: QImage, frame_bgr):
        # 1) stash raw frame for recorder
        self.latest_frame = frame_bgr

        # 2) convert to pixmap & store full‐res
        pix = QPixmap.fromImage(img)
        self._last_pixmap = pix

        # 3) letterbox‐scale into the label
        self._update_video_label()

    def _toggle_serial(self):
        if not self._serial_thread:
            port=self.port_combo.currentData()
            if not port: self._append_console("⚠️ No port selected!");return
            self._serial_thread=SerialThread(port=port,baud=115200)
            self._serial_thread.data_ready.connect(self._update_plot)
            self._serial_thread.start()
            self._append_console(f"🔗 Connected to {port}")
            self.actConnect.setText("Disconnect")
            self.actInit.setEnabled(True);self.actStart.setEnabled(True)
        else:
            self._serial_thread.stop();self._serial_thread=None
            self.actConnect.setText("Connect");self.actInit.setEnabled(False);self.actStart.setEnabled(False)

    def _send_init(self):
        if self._serial_thread and getattr(self._serial_thread,'ser',None):
            self._serial_thread.ser.write(b"CAM_TRIG\n")
            self.sync_icon.setText("Sync: ❓");self._append_console("→ CAM_TRIG")

    def _start_trial(self):
        basepath,_=QFileDialog.getSaveFileName(self,"Save Trial As…","","Base name (no extension)")
        if not basepath: return
        self.times.clear();self.pressures.clear();self.frames.clear();self._t0=None
        self.ax.cla();self.line,=self.ax.plot([],[], '-')
        self.trial_recorder=TrialRecorder(basepath,fps=30,frame_size=(640,480))
        self.actStart.setEnabled(False);self.actStop.setEnabled(True)

    def _stop_trial(self):
        if self.trial_recorder: self.trial_recorder.stop();self.trial_recorder=None
        self.actStart.setEnabled(True);self.actStop.setEnabled(False)

    def _send_serial_cmd(self,cmd:bytes):
        if self._serial_thread and getattr(self._serial_thread,'ser',None):
            self._serial_thread.ser.write(cmd);self._append_console(f"→ {cmd.decode().strip()}")

    def _on_console_send(self):
        txt=self.console_input.text().strip()
        if txt: self._send_serial_cmd(txt.encode()+b"\n");self.console_input.clear()

    def _append_console(self,line:str): self.console_output.append(line)

    def _update_plot(self,frame:int,t:float,p:float):
        if self._t0 is None: self._t0=t
        t_rel=t-self._t0; self.frames.append(frame)
        self.times.append(t_rel);self.pressures.append(p)
        self.line.set_data(self.times,self.pressures)
        # x-axis
        if self.plot_auto_x:
            self.ax.set_xlim(0, max(self.times)+1)
        else:
            xmin,xmax=self.plot_xlim; self.ax.set_xlim(xmin, xmax)
        # y-axis
        if self.plot_auto_y:
            low,high=min(self.pressures),max(self.pressures)
            self.ax.set_ylim(low-1,high+1)
        else:
            ymin,ymax=self.plot_ylim; self.ax.set_ylim(ymin,ymax)
        self.canvas.draw()
        self._append_console(f"{frame}, {t_rel:.3f}, {p:.2f}")
        if self.trial_recorder:
            exp=self.trial_recorder.video_frame_count
            self.sync_icon.setText("Sync: 🔴" if abs(exp-frame)>1 else "Sync: 🟢")

    def _show_camera_settings(self):
        dlg=QDialog(self);dlg.setWindowTitle("Camera Settings")
        form=QFormLayout(dlg)
        w_spin=QSpinBox();w_spin.setRange(100,4096)
        h_spin=QSpinBox();h_spin.setRange(100,4096)
        if hasattr(self.video_thread,'cap') and self.video_thread.cap:
            w_spin.setValue(int(self.video_thread.cap.get(cv2.CAP_PROP_FRAME_WIDTH)))
            h_spin.setValue(int(self.video_thread.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        b_spin=QDoubleSpinBox();b_spin.setRange(0.0,1.0);b_spin.setSingleStep(0.01)
        c_spin=QDoubleSpinBox();c_spin.setRange(0.0,1.0);c_spin.setSingleStep(0.01)
        g_spin=QDoubleSpinBox();g_spin.setRange(0.0,1.0);g_spin.setSingleStep(0.01)
        form.addRow("Width:", w_spin); form.addRow("Height:", h_spin)
        form.addRow("Brightness:", b_spin); form.addRow("Contrast:", c_spin)
        form.addRow("Gain:", g_spin)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept);buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec_()==QDialog.Accepted:
            cap=self.video_thread.cap
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, w_spin.value())
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h_spin.value())
            cap.set(cv2.CAP_PROP_BRIGHTNESS, b_spin.value())
            cap.set(cv2.CAP_PROP_CONTRAST, c_spin.value())
            cap.set(cv2.CAP_PROP_GAIN, g_spin.value())

    def _show_plot_settings(self):
        dlg=QDialog(self);dlg.setWindowTitle("Plot Axis Settings")
        form=QFormLayout(dlg)
        ax_auto=QCheckBox();ax_auto.setChecked(self.plot_auto_x)
        ay_auto=QCheckBox();ay_auto.setChecked(self.plot_auto_y)
        xmin=QDoubleSpinBox();xmax=QDoubleSpinBox()
        ymin=QDoubleSpinBox();ymax=QDoubleSpinBox()
        xmin.setValue(0);xmax.setValue(self.plot_xlim[1] or 10)
        ymin.setValue(self.plot_ylim[0]);ymax.setValue(self.plot_ylim[1])
        form.addRow("Auto X-axis:", ax_auto)
        form.addRow("X-min:", xmin); form.addRow("X-max:", xmax)
        form.addRow("Auto Y-axis:", ay_auto)
        form.addRow("Y-min:", ymin); form.addRow("Y-max:", ymax)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept);buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec_()==QDialog.Accepted:
            self.plot_auto_x=ax_auto.isChecked()
            self.plot_auto_y=ay_auto.isChecked()
            self.plot_xlim=(xmin.value(),xmax.value())
            self.plot_ylim=(ymin.value(),ymax.value())

    def _show_metadata_dialog(self):
        dlg=QDialog(self);dlg.setWindowTitle("New Session Metadata")
        form=QFormLayout(dlg)
        self.meta_name=QLineEdit();self.meta_drug=QLineEdit()
        self.meta_conc=QSpinBox();self.meta_conc.setSuffix(" µM")
        self.meta_type=QComboBox();self.meta_type.addItems(["Control","TTX","Capsaicin"])
        form.addRow("Trial Name:",self.meta_name)
        form.addRow("Drug:",self.meta_drug)
        form.addRow("Concentration:",self.meta_conc)
        form.addRow("Type:",self.meta_type)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept);buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec_()==QDialog.Accepted:
            self.status.showMessage(f"Metadata set: {self.meta_name.text()}",3000)

    def _update_status(self):
        self._elapsed+=1
        parts=[]
        if self.trial_recorder: parts.append(f"Trial: {self.trial_recorder.basepath}")
        parts.append(f"Elapsed: {self._elapsed}s")
        parts.append(self.sync_icon.text())
        self.status.showMessage(" | ".join(parts))

    def closeEvent(self, event):
        if self._serial_thread:
            self._serial_thread.stop()
        if hasattr(self, "video_thread"):
            self.video_thread.stop()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())

