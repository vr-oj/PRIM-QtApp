import os
import numpy as np
import tifffile
from prim_app.recording_manager import RecordingManager

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

