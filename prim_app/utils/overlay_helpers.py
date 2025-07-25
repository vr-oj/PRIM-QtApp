import os
import numpy as np
import pandas as pd
from tifffile import TiffFile, TiffWriter, imwrite
from PIL import Image, ImageDraw, ImageFont


def embed_metadata(tiff_path, csv_path):
    """Embed per-frame pressure in the ImageDescription tag of each page."""
    df = pd.read_csv(csv_path)
    with TiffFile(tiff_path) as tif:
        frames = [page.asarray() for page in tif.pages]

    output_path = tiff_path.replace(".tif", "_metadata.tif")

    with TiffWriter(output_path, bigtiff=True) as out:
        for frame, row in zip(frames, df.itertuples()):
            desc = f"Pressure={row.pressure:.2f} mmHg"
            out.write(frame, description=desc)

    return output_path


def burn_overlay(tiff_path, csv_path, font_size=24, position="Top-Left"):
    """Draw pressure text on each frame and save a new TIFF."""
    corner_offsets = {
        "Top-Left": (10, 10),
        "Top-Right": (-10, 10),
        "Bottom-Left": (10, -10),
        "Bottom-Right": (-10, -10),
    }
    x_off, y_off = corner_offsets.get(position, (10, 10))

    with TiffFile(tiff_path) as tif:
        frames = [page.asarray() for page in tif.pages]

    df = pd.read_csv(csv_path).sort_values("frameIdx").reset_index(drop=True)
    pressures = df["pressure"].values

    if len(frames) != len(pressures):
        raise ValueError(f"{len(frames)} TIFF frames ≠ {len(pressures)} pressure values")

    overlaid = []
    for frame, pressure in zip(frames, pressures):
        img = Image.fromarray(frame)
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("Arial.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

        text = f"{pressure:.2f} mmHg"
        w, h = draw.textsize(text, font=font)
        x = x_off if x_off >= 0 else frame.shape[1] + x_off - w
        y = y_off if y_off >= 0 else frame.shape[0] + y_off - h
        draw.text((x, y), text, fill=255, font=font)
        overlaid.append(np.array(img))

    output_path = tiff_path.replace(".tif", "_overlay.tif").replace(".tiff", "_overlay.tiff")
    imwrite(output_path, np.stack(overlaid), photometric="minisblack", compression="none")
    return output_path
