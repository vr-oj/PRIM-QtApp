import sys
import os
import pandas as pd
import numpy as np
from tifffile import TiffFile, TiffWriter
from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox


def ijv_text_overlay_metadata(text, x, y, index):
    """Create FIJI-compatible ImageJ Text ROI metadata"""
    return {
        "roi": {
            "name": f"pressure_{index}",
            "type": "text",
            "text": text,
            "position": index + 1,
            "x": x,
            "y": y,
            "width": 1,
            "height": 1,
            "stroke-width": 1,
            "font-size": 60,
            "font-name": "SansSerif",
        }
    }


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

        # Output path
        output_path = tiff_path.replace(".tif", "_roi.tif").replace(
            ".tiff", "_roi.tiff"
        )
        print(f"Saving to {output_path}...")

        # Prepare metadata ROIs
        metadata_list = []
        for i, pressure in enumerate(pressures):
            label = f"{pressure:.2f} mmHg"
            metadata_list.append(ijv_text_overlay_metadata(label, x=10, y=20, index=i))

        # Write with overlays (use ImageJ-style metadata)
        TiffWriter(output_path, imagej=True).write(
            data=np.array(frames),
            metadata={"overlays": metadata_list},
            photometric="minisblack",
        )

        QMessageBox.information(
            None, "Done", f"Overlayed ROI TIFF saved:\n\n{output_path}"
        )
        print("✅ Finished.")

    except Exception as e:
        QMessageBox.critical(None, "Error", str(e))
        print("❌ Error:", e)


if __name__ == "__main__":
    run_overlay_converter()
