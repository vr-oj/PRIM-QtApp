"""Minimal fallback for ImageJ ROI writing.

This stub provides a small subset of the `ijroi` package so that ROI
files can be generated without the external dependency.  If the real
``ijroi`` package is installed it will be used instead.
"""

import struct
from dataclasses import dataclass

@dataclass
class TextRoi:
    x: int
    y: int
    text: str
    font_size: int = 18
    position: int = 1
    name: str = "Text"

    def to_bytes(self) -> bytes:
        HEADER_SIZE = 64
        VERSION = 227
        ROI_TYPE_TEXT = 128
        FONT_NAME = "Helvetica"

        data = bytearray(HEADER_SIZE)

        def put_short(i, v):
            struct.pack_into(">H", data, i, v)

        def put_int(i, v):
            struct.pack_into(">I", data, i, v)

        put_short(0, 0x494a)  # 'IJ'
        put_short(2, VERSION)
        data[6] = ROI_TYPE_TEXT
        put_short(8, self.y)
        put_short(10, self.x)
        put_short(12, self.y + 10)
        put_short(14, self.x + 10)
        put_short(16, 1)
        put_int(56, self.position)

        text_bytes = self.text.encode("utf-16-be")
        font_bytes = FONT_NAME.encode("utf-16-be")

        block = bytearray()
        block += struct.pack(">I", len(text_bytes)) + text_bytes
        block += struct.pack(">I", len(font_bytes)) + font_bytes
        block += struct.pack(">i", self.font_size)

        return data + block

def write_roi(roi: TextRoi, path: str):
    with open(path, "wb") as f:
        f.write(roi.to_bytes())

def roi_to_bytes(roi: TextRoi) -> bytes:
    """Return the binary ROI representation."""
    return roi.to_bytes()
