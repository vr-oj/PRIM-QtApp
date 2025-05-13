# main_window.py

import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QLabel, QHBoxLayout, QToolBar, QAction,
    QComboBox  # for port dropdown
)
from PyQt5.QtGui import QImage, QPixmap
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# ——— pull in our refactored modules —————————————————————
from threads.video_thread import VideoThread
from threads.serial_thread import SerialThread
from utils import list_serial_ports


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PRIM Live View")
        self._serial_thread = None
        self._video_thread = None
        self._video_writer = None
        self._csv_file = None

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

        # Toolbar
        tb = QToolBar("Main Toolbar")
        self.addToolBar(tb)

        # — Port selector dropdown instead of QFileDialog — 
        self.port_combo = QComboBox()
        for port, desc in list_serial_ports():
            self.port_combo.addItem(f"{port} ({desc})", port)
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

    def _start_video_thread(self):
        self.video_thread = VideoThread(camera_index=0)
        self.video_thread.frame_ready.connect(self._update_image)
        self.video_thread.start()

    def _toggle_serial(self):
        if not self._serial_thread:
            port = self.port_combo.currentData()
            if not port:
                return
            self._serial_thread = SerialThread(port=port, baud=115200)
            self._serial_thread.data_ready.connect(self._update_plot)
            self._serial_thread.start()
            self.actConnect.setText("Disconnect")
            self.actInit.setEnabled(True)
            self.actStart.setEnabled(True)
        else:
            self._serial_thread.stop()
            self._serial_thread = None
            self.actConnect.setText("Connect")
            self.actInit.setEnabled(False)
            self.actStart.setEnabled(False)

    def _send_init(self):
        if self._serial_thread and self._serial_thread.ser:
            self._serial_thread.ser.write(b"CAM_TRIG\n")

    def _start_trial(self):
        # TODO: hook in TrialRecorder from recording.py
        self.actStart.setEnabled(False)
        self.actStop.setEnabled(True)

    def _stop_trial(self):
        # TODO: stop the recorder
        self.actStart.setEnabled(True)
        self.actStop.setEnabled(False)

    def _update_image(self, img: QImage):
        self.video_label.setPixmap(QPixmap.fromImage(img))

    def _update_plot(self, t: float, p: float):
        # existing plotting logic…
        pass

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
