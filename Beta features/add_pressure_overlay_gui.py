import sys
import os
import pandas as pd
import numpy as np
from tifffile import TiffFile, imwrite
from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox
from PIL import Image, ImageDraw, ImageFont


def draw_text_overlay(frame, text, position=(10, 20), font_size=80):
    """Draw text on a grayscale frame using PIL"""
    img = Image.fromarray(frame)
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("Arial.ttf", font_size)
    except:
        font = ImageFont.load_default()

    draw.text(position, text, fill=255, font=font)
    return np.array(img)


def run_overlay_converter():
    app = QApplication(sys.argv)

    tiff_path, _ = QFileDialog.getOpenFileName(
        None, "Select TIFF File", "", "TIFF files (*.tif *.tiff)"
    )
    if not tiff_path:
        return

    csv_path, _ = QFileDialog.getOpenFileName(
        None, "Select Pressure CSV File", "", "CSV files (*.csv)"
    )
    if not csv_path:
        return

    try:
        with TiffFile(tiff_path) as tif:
            frames = [page.asarray() for page in tif.pages]
        print(f"Loaded {len(frames)} frames from TIFF.")

        df = pd.read_csv(csv_path)
        if "pressure" not in df.columns or "frameIdx" not in df.columns:
            raise ValueError("CSV must contain 'frameIdx' and 'pressure' columns.")

        df_sorted = df.sort_values(by="frameIdx").reset_index(drop=True)
        pressures = df_sorted["pressure"].values

        if len(frames) != len(pressures):
            raise ValueError(
                f"{len(frames)} TIFF frames ≠ {len(pressures)} pressure values"
            )

        # Apply overlay
        print("Applying text overlays...")
        overlaid_frames = []
        for frame, pressure in zip(frames, pressures):
            label = f"{pressure:.2f} mmHg"
            frame_with_text = draw_text_overlay(frame, label)
            overlaid_frames.append(frame_with_text)

        output_path = tiff_path.replace(".tif", "_overlay.tif").replace(
            ".tiff", "_overlay.tiff"
        )
        print(f"Saving to {output_path}...")

        imwrite(
            output_path,
            np.array(overlaid_frames),
            photometric="minisblack",
            compression="none",
        )

        QMessageBox.information(None, "Done", f"Overlayed TIFF saved:\n\n{output_path}")
        print("✅ Finished.")

    except Exception as e:
        QMessageBox.critical(None, "Error", str(e))
        print("❌ Error:", e)


if __name__ == "__main__":
    run_overlay_converter()
