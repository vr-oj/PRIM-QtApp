import sys
import os
import pandas as pd
from tifffile import TiffFile, TiffWriter
from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox


def run_converter():
    app = QApplication(sys.argv)

    # Step 1: Select TIFF file
    tiff_path, _ = QFileDialog.getOpenFileName(
        None, "Select TIFF File", "", "TIFF files (*.tif *.tiff)"
    )
    if not tiff_path:
        return

    # Step 2: Select CSV file
    csv_path, _ = QFileDialog.getOpenFileName(
        None, "Select Pressure CSV File", "", "CSV files (*.csv)"
    )
    if not csv_path:
        return

    try:
        # Load all frames using page-by-page read (guaranteed full stack)
        print(f"Loading TIFF: {tiff_path}")
        with TiffFile(tiff_path) as tif:
            frames = [page.asarray() for page in tif.pages]
        print(f"Loaded {len(frames)} frames with shape: {frames[0].shape}")

        # Load pressure CSV
        print(f"Loading CSV: {csv_path}")
        df = pd.read_csv(csv_path)

        if "pressure" not in df.columns or "frameIdx" not in df.columns:
            raise ValueError("CSV must contain 'frameIdx' and 'pressure' columns.")

        df_sorted = df.sort_values(by="frameIdx").reset_index(drop=True)
        pressures = df_sorted["pressure"].values

        if len(frames) != len(pressures):
            raise ValueError(
                f"{len(frames)} TIFF frames ≠ {len(pressures)} pressure values in CSV"
            )

        # Output path
        base, ext = os.path.splitext(tiff_path)
        output_path = base + "_with_pressure.tiff"

        print(f"Saving output to: {output_path}")
        with TiffWriter(output_path, bigtiff=True) as tif:
            for i, (frame, pressure) in enumerate(zip(frames, pressures)):
                desc = f"Pressure={pressure:.2f} mmHg"
                tif.write(frame, description=desc)

        QMessageBox.information(
            None, "Success", f"New TIFF saved with pressure metadata:\n\n{output_path}"
        )
        print("✅ Done")

    except Exception as e:
        QMessageBox.critical(None, "Error", str(e))
        print("❌ Error:", e)


if __name__ == "__main__":
    run_converter()
