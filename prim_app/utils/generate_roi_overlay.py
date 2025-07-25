import pandas as pd
import os
import zipfile
from ijroi import ROIEncoder, TextRoi


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
        encoder = ROIEncoder()
        for _, row in df.iterrows():
            frame = int(row['frameIdx'])
            pressure = row['pressure']

            text = f"{pressure:.2f} mmHg"
            x, y = x_offset, y_offset

            roi = TextRoi(x, y, text, font_size=font_size)
            roi.set_position(frame)

            roi_bytes = encoder.encode(roi)
            name = f"Frame_{frame:05d}.roi"
            zf.writestr(name, roi_bytes)

    print(f"✅ ROI ZIP saved: {output_zip_path}")
    return output_zip_path
