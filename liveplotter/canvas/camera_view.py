# camera_view.py

import numpy as np
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import QTimer

try:
    import imagingcontrol4 as ic4

    IC4_AVAILABLE = True
except ImportError:
    IC4_AVAILABLE = False
    import cv2


class CameraView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.label = QLabel("Camera Feed")
        self.label.setStyleSheet("background-color: black;")
        self.label.setScaledContents(True)

        layout = QVBoxLayout()
        layout.addWidget(self.label)
        self.setLayout(layout)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)

        self.ic4_device = None
        self.opencv_cap = None

    def start_camera(self):
        if IC4_AVAILABLE:
            devices = ic4.Device.enumerate()
            if not devices:
                print("No IC4 devices found.")
                return
            self.ic4_device = devices[0].open()
            fmt = self.ic4_device.videoFormats()[0]
            self.ic4_device.setVideoFormat(fmt)
            self.sink = self.ic4_device.sink()
            self.stream = self.ic4_device.stream()
            self.stream.start()
            print("IC4 camera started.")
        else:
            self.opencv_cap = cv2.VideoCapture(0)
            if not self.opencv_cap.isOpened():
                print("OpenCV camera not available.")
                return
            print("OpenCV camera started.")

        self.timer.start(30)

    def stop_camera(self):
        self.timer.stop()
        if IC4_AVAILABLE and self.ic4_device:
            self.stream.stop()
            self.ic4_device.close()
            self.ic4_device = None
        elif self.opencv_cap:
            self.opencv_cap.release()
            self.opencv_cap = None

    def update_frame(self):
        if IC4_AVAILABLE and self.ic4_device:
            frame = self.sink.snap()
            image = QImage(
                frame.data(), frame.width(), frame.height(), QImage.Format_RGB888
            )
        elif self.opencv_cap:
            ret, frame = self.opencv_cap.read()
            if not ret:
                return
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = frame.shape
            image = QImage(frame.data, w, h, ch * w, QImage.Format_RGB888)
        else:
            return

        self.label.setPixmap(QPixmap.fromImage(image))
