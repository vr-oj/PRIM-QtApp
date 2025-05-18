import imagingcontrol4 as ic4
import numpy as np
from PyQt5.QtGui import QImage

# --------------- POC: grab one frame and convert to QImage ---------------
ic4.Library.init()

grabber = ic4.Grabber()
devices = grabber.get_device_list()
grabber.set_device(devices[0])  # pick the first DMK 33UX250
grabber.set_property("ExposureTime", 20000)  # adjust as needed

grabber.start()
frame = grabber.grab_image()  # NumPy array (H×W×channels)
grabber.stop()

# Convert to QImage (for direct use in your Qt widget)
h, w = frame.shape[:2]
bytes_per_line = frame.strides[0]
img = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)

grabber.close()
ic4.Library.exit()

# If this runs without error, you can pass `img` straight to your QtCameraWidget
