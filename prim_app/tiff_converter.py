import pandas as pd
from tifffile import imread, TiffWriter
from PyQt5.QtWidgets import QFileDialog, QMessageBox


def convert_tiff_with_pressure_metadata(parent_widget=None):
    """Convert an old TIFF using a matching pressure CSV to embed per-frame pressure metadata."""
    # Select original TIFF
    tiff_path, _ = QFileDialog.getOpenFileName(
        parent_widget,
        "Select TIFF File",
        "",
        "TIFF files (*.tif *.tiff)"
    )
    if not tiff_path:
        return

    # Select pressure CSV
    csv_path, _ = QFileDialog.getOpenFileName(
        parent_widget,
        "Select Pressure CSV File",
        "",
        "CSV files (*.csv)"
    )
    if not csv_path:
        return

    try:
        # Load data
        frames = imread(tiff_path)
        df = pd.read_csv(csv_path)

        if "Pressure" not in df.columns:
            raise ValueError("CSV must contain a 'Pressure' column.")

        pressures = df["Pressure"].values

        if len(frames) != len(pressures):
            raise ValueError(f"{len(frames)} TIFF frames ≠ {len(pressures)} pressure values.")

        out_path = (
            tiff_path.replace(".tif", "_with_pressure.tif").replace(".tiff", "_with_pressure.tiff")
        )

        with TiffWriter(out_path) as tif:
            for frame, p in zip(frames, pressures):
                tif.write(frame, description=f"Pressure={p:.1f} mmHg")

        QMessageBox.information(parent_widget, "Success", f"Saved: {out_path}")

    except Exception as e:
        QMessageBox.critical(parent_widget, "Error", str(e))
