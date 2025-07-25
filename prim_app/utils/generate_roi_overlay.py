import pandas as pd
import os
import zipfile

try:
    from ijroi import TextRoi, roi_to_bytes
except Exception:  # pragma: no cover - fallback when ijroi is missing
    from .ijroi_stub import TextRoi, roi_to_bytes


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

    with zipfile.ZipFile(output_zip_path, "w") as zf:
        for _, row in df.iterrows():
            frame = int(row["frameIdx"])
            pressure = row["pressure"]
            name = f"frame{frame:05d}.roi"

            x, y = x_offset, y_offset

            # Fiji's ROI format only stores the slice number as a 16-bit value
            position_idx = min(frame, 65535)

            roi = TextRoi(x, y, str(pressure), font_size=font_size, position=position_idx, name=name)
            zf.writestr(name, roi_to_bytes(roi))

    print(f"✅ ROI ZIP saved: {output_zip_path}")
    return output_zip_path
