import pandas as pd
import os
import struct
import zipfile


def generate_overlay_zip(csv_path, output_zip_path=None, font_size=18, position="Top-Left"):
    df = pd.read_csv(csv_path)

    if 'frameIdx' not in df.columns or 'pressure' not in df.columns:
        raise ValueError("CSV must contain 'frameIdx' and 'pressure' columns.")

    base_name = os.path.splitext(os.path.basename(csv_path))[0].replace("_pressure", "")
    if output_zip_path is None:
        output_zip_path = os.path.join(os.path.dirname(csv_path), f"{base_name}_overlays.zip")

    corner_offsets = {
        "Top-Left": (10, 10),
        "Top-Right": (-10, 10),
        "Bottom-Left": (10, -10),
        "Bottom-Right": (-10, -10),
    }
    x_offset, y_offset = corner_offsets.get(position, (10, 10))

    with zipfile.ZipFile(output_zip_path, 'w') as zf:
        for _, row in df.iterrows():
            frame = int(row['frameIdx'])
            pressure = row['pressure']
            name = f"frame{frame:05d}.roi"

            x, y = x_offset, y_offset

            roi = create_text_roi(name, x, y, str(pressure), font_size, frame)
            zf.writestr(name, roi)

    print(f"✅ ROI ZIP saved: {output_zip_path}")
    return output_zip_path


def create_text_roi(name, x, y, text, font_size, position):
    HEADER_SIZE = 64
    VERSION = 227
    ROI_TYPE_TEXT = 128
    FONT_NAME = "Helvetica"

    roi_data = bytearray(HEADER_SIZE)

    def put_short(index, value):
        struct.pack_into(">H", roi_data, index, value)

    def put_int(index, value):
        struct.pack_into(">I", roi_data, index, value)

    # Header (magic 'Iout')
    put_short(0, 0x494a)  # 'IJ'
    put_short(2, VERSION)

    # Type and basic bounds
    roi_data[6] = ROI_TYPE_TEXT
    put_short(8, y)
    put_short(10, x)
    put_short(12, y + 10)
    put_short(14, x + 10)
    put_short(16, 1)

    # Set position (slice number, 1-based)
    put_int(56, position)

    # Extended header with text and font info
    text_bytes = text.encode('utf-16-be')
    font_bytes = FONT_NAME.encode('utf-16-be')

    text_block = bytearray()
    text_block += struct.pack(">I", len(text_bytes)) + text_bytes
    text_block += struct.pack(">I", len(font_bytes)) + font_bytes
    text_block += struct.pack(">i", font_size)

    return roi_data + text_block
