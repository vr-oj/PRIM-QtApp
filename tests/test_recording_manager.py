import os
import numpy as np
import tifffile
from prim_app.recording_manager import RecordingManager


class FakeBits(bytearray):
    def setsize(self, size):
        pass


class FakeQImage:
    Format_Grayscale8 = object()
    Format_Indexed8 = object()
    Format_ARGB32 = object()

    def __init__(self, data, fmt):
        self._data = data
        self._fmt = fmt

    def format(self):
        return self._fmt

    def width(self):
        return self._data.shape[1]

    def height(self):
        return self._data.shape[0]

    def bits(self):
        return FakeBits(self._data.tobytes())

    def byteCount(self):
        return self._data.nbytes

    def convertToFormat(self, fmt):
        assert fmt is self.Format_ARGB32
        if self._data.ndim == 2:
            h, w = self._data.shape
            arr = np.zeros((h, w, 4), dtype=np.uint8)
            arr[:, :, 0] = self._data
            arr[:, :, 1] = self._data
            arr[:, :, 2] = self._data
            arr[:, :, 3] = 255
        else:
            arr = self._data
        return FakeQImage(arr, self.Format_ARGB32)

def test_recording_manager_simple(tmp_path, monkeypatch):
    rm = RecordingManager(output_dir=tmp_path)
    rm.start_recording()
    monkeypatch.setattr(rm, "_qimage_to_numpy", lambda qimg: np.zeros((2, 2), dtype=np.uint8))
    for i in range(3):
        rm.append_pressure(i, i * 0.1, float(i))
        rm.append_frame(None, None)
    rm.stop_recording()
    with tifffile.TiffFile(rm._tiff_path) as tf:
        assert len(tf.pages) == 3


def test_qimage_to_numpy_grayscale(tmp_path):
    rm = RecordingManager(output_dir=tmp_path)
    data = np.arange(9, dtype=np.uint8).reshape((3, 3))
    qimg = FakeQImage(data, FakeQImage.Format_Grayscale8)
    arr = rm._qimage_to_numpy(qimg)
    assert arr.shape == data.shape
    assert np.array_equal(arr, data)

