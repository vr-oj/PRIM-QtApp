import csv


def write_recording_csv_metadata_and_header(
    csv_writer,
    recording_fps,
    frame_interval_ms,
    capture_setting_label,
    capture_setting_code,
):
    csv_writer.writerow(["# recording_fps", recording_fps])
    csv_writer.writerow(["# frame_interval_ms", frame_interval_ms])
    csv_writer.writerow(["# capture_setting", capture_setting_label])
    csv_writer.writerow(["# capture_setting_code", capture_setting_code])
    csv_writer.writerow(["frameIdx", "deviceTime", "pressure", "tiffFrame"])


def iter_csv_data_lines(csv_file):
    """Yield CSV table lines while skipping metadata comments."""
    for line in csv_file:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        yield line


def load_pressure_values(csv_path):
    with open(csv_path, "r", newline="") as f:
        reader = csv.DictReader(iter_csv_data_lines(f))
        rows = list(reader)

    has_tiff_frame_column = bool(rows and "tiffFrame" in rows[0])
    if has_tiff_frame_column:
        tiff_rows = [
            row for row in rows
            if str(row.get("tiffFrame", "")).strip()
        ]
        if tiff_rows:
            tiff_rows.sort(key=lambda row: int(row.get("tiffFrame", 0)))
            return [float(row.get("pressure", 0)) for row in tiff_rows]

    return [float(row.get("pressure", 0)) for row in rows]
