import sys, cv2
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel,
    QHBoxLayout, QVBoxLayout, QToolBar, QAction,
    QComboBox, QFileDialog, QDockWidget,
    QTextEdit, QLineEdit, QPushButton,
    QStatusBar, QDialog, QFormLayout,
    QDialogButtonBox, QSpinBox
)
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import Qt, QTimer
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

        self.times = []        # will hold all incoming timestamps
        self.pressures = []    # will hold all incoming pressure values

        self._serial_thread = None
        self._video_thread = None
        self._video_writer = None
        self._csv_file = None
        self.trial_recorder = None

        self._build_ui()
        self._start_video_thread()


    def _build_ui(self):
        # Central widget: video + plot
        central = QWidget()
        self.video_label = QLabel()
        self.video_label.setFixedSize(640, 480)

        self.fig = Figure(figsize=(5, 4))
        self.ax = self.fig.add_subplot(111)
        self.line, = self.ax.plot([], [], '-')
        self.canvas = FigureCanvas(self.fig)

        hl = QHBoxLayout()
        hl.addWidget(self.video_label)
        hl.addWidget(self.canvas)
        central.setLayout(hl)
        self.setCentralWidget(central)

        # Console dock
        self.console_dock = QDockWidget("Console", self)
        self.console_dock.setAllowedAreas(Qt.BottomDockWidgetArea)
        self.console_widget = QWidget()
        v = QVBoxLayout(self.console_widget)
        self.console_output = QTextEdit()
        self.console_output.setReadOnly(True)
        h = QHBoxLayout()
        self.console_input = QLineEdit()
        btn_send = QPushButton("Send")
        btn_send.clicked.connect(self._on_console_send)
        h.addWidget(self.console_input)
        h.addWidget(btn_send)
        v.addWidget(self.console_output)
        v.addLayout(h)
        self.console_dock.setWidget(self.console_widget)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.console_dock)
        self.console_dock.setFixedHeight(150)

        # Toolbar
        tb = QToolBar("Main Toolbar")
        self.addToolBar(tb)

        # 1) Create the port dropdown
        self.port_combo = QComboBox()

        # 2) Add a simulated‑data option
        self.port_combo.addItem("🔧 Simulated Data", None)

        # 3) Populate with real serial ports
        for port, desc in list_serial_ports():
            self.port_combo.addItem(f"{port} ({desc})", port)

        # 4) Add the dropdown to the toolbar
        tb.addWidget(self.port_combo)

        # Connect / Disconnect
        self.actConnect = QAction("Connect", self)
        self.actConnect.triggered.connect(self._toggle_serial)
        tb.addAction(self.actConnect)

        # Init (CamTrig pulse)
        self.actInit = QAction("Init", self)
        self.actInit.setEnabled(False)
        self.actInit.triggered.connect(self._send_init)
        tb.addAction(self.actInit)

        # Start Trial
        self.actStart = QAction("Start Trial", self)
        self.actStart.setEnabled(False)
        self.actStart.triggered.connect(self._start_trial)
        tb.addAction(self.actStart)

        # Stop Trial
        self.actStop = QAction("Stop Trial", self)
        self.actStop.setEnabled(False)
        self.actStop.triggered.connect(self._stop_trial)
        tb.addAction(self.actStop)

        # Pump controls
        self.actPumpOn = QAction("Pump On", self)
        self.actPumpOn.triggered.connect(lambda: self._send_serial_cmd(b"PUMP_ON\n"))
        tb.addAction(self.actPumpOn)

        self.actPumpOff = QAction("Pump Off", self)
        self.actPumpOff.triggered.connect(lambda: self._send_serial_cmd(b"PUMP_OFF\n"))
        tb.addAction(self.actPumpOff)

        # Sync indicator (start stale, will update later)
        self.sync_icon = QLabel("Sync: ❓")
        tb.addWidget(self.sync_icon)

        # New Trial metadata
        self.actNewTrial = QAction("New Trial", self)
        self.actNewTrial.triggered.connect(self._show_metadata_dialog)
        tb.addAction(self.actNewTrial)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        # Update with a timer every second
        self._elapsed = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_status)
        self._timer.start(1000)

        from utils import list_cameras

        # Camera selector dropdown
        self.cam_combo = QComboBox()
        available = list_cameras(max_idx=4)   # scan indices 0–3
        for idx in available:
            self.cam_combo.addItem(f"Camera {idx}", idx)
        if not available:
            self.cam_combo.addItem("No cameras found", None)
        tb.addWidget(self.cam_combo)


    def _start_video_thread(self):
        idx = self.cam_combo.currentData()
        if idx is None:
            idx = 0  # fallback
        self.video_thread = VideoThread(camera_index=idx)
        self.video_thread.frame_ready.connect(self._on_frame)
        self.video_thread.start()
        self.latest_frame = None

    def _on_frame(self, img: QImage, frame_bgr):
        # 1. display
        self.video_label.setPixmap(QPixmap.fromImage(img))
        # 2. stash raw frame for recording
        self.latest_frame = frame_bgr


    def _toggle_serial(self):
        if not self._serial_thread:
            # Grab the port (None for simulated data)
            port = self.port_combo.currentData()

            # Start the serial thread in either real or simulated mode
            self._serial_thread = SerialThread(port=port, baud=115200)
            self._serial_thread.data_ready.connect(self._update_plot) # signature now is _update_plot(frame, t, p)
            self._serial_thread.start()

            # Update the UI
            self.actConnect.setText("Disconnect")
            self.actInit.setEnabled(True)
            self.actStart.setEnabled(True)
        else:
            # Tear down the existing thread
            self._serial_thread.stop()
            self._serial_thread = None
            self.actConnect.setText("Connect")
            self.actInit.setEnabled(False)
            self.actStart.setEnabled(False)


    def _send_init(self):
        if self._serial_thread and self._serial_thread.ser:
            self._serial_thread.ser.write(b"CAM_TRIG\n")

    def _start_trial(self):
        # 1. Ask user for a base filename
        basepath, _ = QFileDialog.getSaveFileName(
            self, 
            "Save Trial As…", 
            "", 
            "Base name (no extension)"
        )
        if not basepath:
            return

        # 2. Create the recorder (captures both video + CSV)
        #    We assume 30 FPS and your video_label size is 640×480
        self.trial_recorder = TrialRecorder(
            basepath=basepath,
            fps=30,
            frame_size=(640, 480)
        )

        # 3. Toggle UI buttons
        self.actStart.setEnabled(False)
        self.actStop.setEnabled(True)

    def _stop_trial(self):
        if self.trial_recorder:
            self.trial_recorder.stop()
            self.trial_recorder = None

        self.actStart.setEnabled(True)
        self.actStop.setEnabled(False)

    def _update_image(self, img: QImage):
        self.video_label.setPixmap(QPixmap.fromImage(img))

    def _send_serial_cmd(self, cmd: bytes):
        if self._serial_thread and self._serial_thread.ser:
            self._serial_thread.ser.write(cmd)
            self._append_console(f"→ {cmd.decode().strip()}")

    def _on_console_send(self):
        txt = self.console_input.text().strip()
        if not txt: return
        self._send_serial_cmd(txt.encode() + b'\n')
        self.console_input.clear()

    def _append_console(self, line: str):
        self.console_output.append(line)

    def _update_plot(self, t: float, p: float):
        # 1) store the new data
        self.frames.append(frame)
        self.times.append(t)
        self.pressures.append(p)
        # 2) update the plotted line
        self.line.set_data(self.times, self.pressures)
        # 3) rescale axes to fit all data
        self.ax.relim(); self.ax.autoscale_view()
        # 4) redraw
        self.canvas.draw()
        # write to recorder if active
        if self.trial_recorder and self.latest_frame is not None:
            # Note: TrialRecorder.write expects (frame_bgr, t, p)
            self.trial_recorder.write(self.latest_frame, t, p)

        self._append_console(f"{frame}, {t:.2f}, {p:.2f}")
        
        # ---- SYNC CHECK ----
        # compare 'frame' vs. video frame index
        expected = self.trial_recorder.video_frame_count if self.trial_recorder else None
        if expected is not None:
            # if drift >1 frame, red; else green
            if abs(expected - frame) > 1:
                self.sync_icon.setText("Sync: 🔴")
            else:
                self.sync_icon.setText("Sync: 🟢")
        else:
            # no recorder yet, just show neutral
            self.sync_icon.setText("Sync: ❓")

    def _show_metadata_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("New Trial Metadata")
        form = QFormLayout(dlg)
        self.meta_name = QLineEdit()
        self.meta_drug = QLineEdit()
        self.meta_conc = QSpinBox(); self.meta_conc.setSuffix(" µM")
        self.meta_type = QComboBox()
        self.meta_type.addItems(["Control", "TTX", "Capsaicin"])
        form.addRow("Trial Name:", self.meta_name)
        form.addRow("Drug:", self.meta_drug)
        form.addRow("Concentration:", self.meta_conc)
        form.addRow("Type:", self.meta_type)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec_() == QDialog.Accepted:
            name = self.meta_name.text()
            # store or annotate your recorder with these values
            self.status.showMessage(f"Metadata set: {name}", 3000)

    def _update_status(self):
        # Increment elapsed‐seconds counter
        self._elapsed += 1

        # Build a status message
        parts = []

        # If a trial is running, show its base name
        if hasattr(self, 'trial_recorder') and self.trial_recorder:
            # Your TrialRecorder might expose the basepath; adjust as needed
            bp = getattr(self.trial_recorder, 'basepath', 'Unknown')
            parts.append(f"Trial: {bp}")

        # Elapsed time
        parts.append(f"Elapsed: {self._elapsed}s")

        # Sync indicator (you can replace this with real logic)
        parts.append(self.sync_icon.text())

        # Combine and display
        self.status.showMessage(" | ".join(parts))

    def closeEvent(self, event):
        if self._serial_thread:
            self._serial_thread.stop()
        if self.video_thread:
            self.video_thread.stop()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())
