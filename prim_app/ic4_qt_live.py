# File: ic4_qt_live.py

import sys
import numpy as np
import imagingcontrol4 as ic4

from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout
from PyQt5.QtGui     import QImage, QPixmap
from PyQt5.QtCore    import Qt


class QueueSinkDisplay(QWidget):
    """
    A simple QWidget that owns:
      - a QLabel (self.label) for showing live frames
      - a Grabber / QueueSink combo to pull frames from the camera
    """
    def __init__(self, dev_info):
        super().__init__()

        # (1) Basic window setup
        self.setWindowTitle("IC4 Live View")
        self.resize(800, 600)

        # (2) A QLabel to show incoming frames
        self.label = QLabel("Initializing camera…", self)
        self.label.setAlignment(Qt.AlignCenter)
        self.layout = QVBoxLayout(self)
        self.layout.addWidget(self.label)

        # (3) Create and open the Grabber
        self.grabber = ic4.Grabber()
        try:
            self.grabber.device_open(dev_info)
        except ic4.IC4Exception as e:
            # If opening fails, show error in label
            self.label.setText(f"❌ Could not open camera:\n{e}")
            return

        # (4) Pick a PixelFormat that your camera supports.
        #     In our case, "BGRa8" is generally available on Basler USB 3 Vision devices.
        #
        #     You can use device_property_map to print out what your camera really supports,
        #     but for most Basler GigE / USB3 cameras, "BGRa8" is a safe choice.
        #
        pf_node = self.grabber.device_property_map.find_enumeration("PixelFormat")
        if pf_node:
            # If BGRa8 is available, set it:
            entry_names = [e.name for e in pf_node.entries]
            if "BGRa8" in entry_names:
                try:
                    pf_node.value = "BGRa8"
                except Exception:
                    pass

        # (5) Force "Continuous" acquisition mode (if supported)
        acq_node = self.grabber.device_property_map.find_enumeration("AcquisitionMode")
        if acq_node:
            names = [e.name for e in acq_node.entries]
            if "Continuous" in names:
                try:
                    acq_node.value = "Continuous"
                except Exception:
                    pass

        # (6) Start acquisition before attaching the sink:
        try:
            self.grabber.acquisition_start()
        except Exception:
            # if acquisition is already active, ignore
            pass

        # (7) Create a QueueSinkListener and QueueSink, then hook it up to the grabber
        self.listener = self.ProcessAndDisplayListener(self)
        # Pass a list of desired output formats: here we pass [ic4.PixelFormat.BGRa8].
        # max_output_buffers=2 (or more) is usually fine.
        self.sink = ic4.QueueSink(self.listener, [ic4.PixelFormat.BGRa8], max_output_buffers=2)
        try:
            self.grabber.stream_setup(self.sink)
        except ic4.IC4Exception as e:
            self.label.setText(f"❌ Could not setup stream:\n{e}")
            return

    class ProcessAndDisplayListener(ic4.QueueSinkListener):
        """
        A QueueSinkListener that:
          - allocates buffers when sink_connected() is called
          - in frames_queued(), pops the next buffer, turns it into a NumPy array
            and then into a QImage→QPixmap to display in the parent QLabel.
        """
        def __init__(self, parent_widget: "QueueSinkDisplay"):
            self.parent = parent_widget

        def sink_connected(self, sink: ic4.QueueSink, image_type: ic4.ImageType, min_buffers_required: int) -> bool:
            """
            Called once when the sink is attached to the grabber.
            We tell it to allocate and queue the minimum number of buffers.
            """
            try:
                sink.alloc_and_queue_buffers(min_buffers_required)
                return True
            except ic4.IC4Exception as e:
                # If buffer allocation fails, show text in the parent label
                self.parent.label.setText(f"❌ Error allocating buffers:\n{e}")
                return False

        def frames_queued(self, sink: ic4.QueueSink):
            """
            Called every time a new ImageBuffer arrives.
            We pop it, do a numpy_wrap() → QImage → QPixmap → QLabel.setPixmap(…),
            then re‐queue the buffer so IC4 can keep filling it.
            """
            try:
                img_buf = sink.pop_output_buffer()
            except ic4.IC4Exception as e:
                # If grabbing times out or device lost, you could emit an error. For now, ignore.
                return

            # Convert to a NumPy array.  This array is (H, W, 4) in BGRa8 format.
            arr = img_buf.numpy_wrap()  # dtype=uint8, shape=(height, stride, …)
            # `arr` is typically shape (height, stride) or (height, width*4) if no padding.
            # But most APIs guarantee arr.shape = (height, stride). If your buffers have no padding,
            # you can reshape/truncate.  Safe approach: use arr.reshape((H, stride)) then slice to (H, W, 4).
            #
            # However, often .numpy_wrap() already returns exactly (height, width*4).  We can do:
            h, stride = arr.shape[0], arr.shape[1]
            w = int(stride / 4)  # because BGRa8 = 4 bytes/pixel
            try:
                arr2 = arr.reshape((h, stride))[:, : (w * 4)].reshape((h, w, 4))
            except Exception:
                # If reshape fails (rare), fall back to directly interpreting shape:
                arr2 = arr  # hopefully it's already (h, w, 4)
                h, w = arr2.shape[0], arr2.shape[1]

            # Convert BGR → RGB by slicing:
            rgb = arr2[:, :, :3][..., ::-1]  # drop alpha and swap B↔R

            # Build a QImage from the numpy array.  Format_RGB888 expects 3 channels.
            stride_bytes = rgb.strides[0]
            qimg = QImage(
                rgb.data, w, h, stride_bytes, QImage.Format.Format_RGB888
            )
            pix = QPixmap.fromImage(qimg)

            # Display it (scaled) in the parent widget’s QLabel:
            self.parent.label.setPixmap(pix.scaled(
                self.parent.label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            ))

            # Re‐queue the buffer so IC4 can reuse it:
            sink.queue_buffer(img_buf)

        def sink_disconnected(self, sink: ic4.QueueSink):
            """
            Called if the sink is ever detached. We could clean up here.
            """
            pass

    def closeEvent(self, event):
        """
        When the window is closed, stop the stream and close the device.
        """
        try:
            self.grabber.stream_stop()
        except Exception:
            pass
        try:
            self.grabber.device_close()
        except Exception:
            pass
        event.accept()



def main():
    # 1) Initialize the IC4 library (do this exactly once!)
    ic4.Library.init()

    # 2) Enumerate all attached devices:
    device_list = ic4.DeviceEnum.devices()
    if not device_list:
        print("❌ No IC4 devices found.  Exiting.")
        ic4.Library.exit()
        return

    # For simplicity, just pick the first camera:
    dev0 = device_list[0]
    print(f"Using device 0: {dev0.model_name} (S/N {dev0.serial})")

    # 3) Start Qt in order to show live frames:
    app = QApplication(sys.argv)
    win = QueueSinkDisplay(dev0)
    win.show()
    app.exec()

    # 4) After the Qt loop exits, be sure to call Library.exit()
    ic4.Library.exit()


if __name__ == "__main__":
    main()