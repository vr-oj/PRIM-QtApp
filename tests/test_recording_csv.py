import csv
import io
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prim_app"))

from utils.recording_csv import (
    load_pressure_values,
    write_recording_csv_metadata_and_header,
)
from utils.recording_settings import build_recording_settings


class RecordingCsvTests(unittest.TestCase):
    def _render_csv_lines(self, settings, rows):
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        write_recording_csv_metadata_and_header(
            writer,
            settings.recording_fps,
            settings.frame_interval_ms,
            settings.capture_setting_label,
            settings.capture_setting_code,
        )
        for row in rows:
            writer.writerow(row)
        return buffer.getvalue().splitlines()

    def test_csv_only_metadata_and_row_shape(self):
        settings = build_recording_settings(9, 0)
        lines = self._render_csv_lines(settings, [[1, 0.25, 12.5, ""]])

        self.assertEqual(lines[0], "# recording_fps,9.0")
        self.assertEqual(lines[1], "# frame_interval_ms,112")
        self.assertEqual(lines[2], "# capture_setting,None")
        self.assertEqual(lines[3], "# capture_setting_code,0")
        self.assertEqual(lines[4], "frameIdx,deviceTime,pressure,tiffFrame")
        self.assertEqual(lines[5], "1,0.25,12.5,")

    def test_video_recording_metadata_and_row_shape(self):
        settings = build_recording_settings(10, 1)
        lines = self._render_csv_lines(settings, [[2, 0.5, 18.75, 1]])

        self.assertEqual(
            lines[:5],
            [
                "# recording_fps,10.0",
                "# frame_interval_ms,100",
                "# capture_setting,Every",
                "# capture_setting_code,1",
                "frameIdx,deviceTime,pressure,tiffFrame",
            ],
        )
        self.assertEqual(lines[5], "2,0.5,18.75,1")

    def test_load_pressure_values_supports_old_and_metadata_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_csv = Path(tmpdir) / "old.csv"
            old_csv.write_text(
                "frameIdx,deviceTime,pressure\n"
                "1,0.1,7.5\n"
                "2,0.2,8.5\n"
            )

            new_csv = Path(tmpdir) / "new.csv"
            new_csv.write_text(
                "# recording_fps,10.0\n"
                "# frame_interval_ms,100\n"
                "# capture_setting,Every\n"
                "# capture_setting_code,1\n"
                "frameIdx,deviceTime,pressure,tiffFrame\n"
                "1,0.1,7.5,1\n"
                "2,0.2,8.5,2\n"
            )

            self.assertEqual(load_pressure_values(old_csv), [7.5, 8.5])
            self.assertEqual(load_pressure_values(new_csv), [7.5, 8.5])

    def test_load_pressure_values_uses_marked_tiff_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "capture_1_in_10.csv"
            csv_path.write_text(
                "frameIdx,deviceTime,pressure,tiffFrame\n"
                "1,0.0,1.0,\n"
                "2,0.1,2.0,\n"
                "3,0.2,3.0,1\n"
                "4,0.3,4.0,\n"
                "5,0.4,5.0,2\n"
            )

            self.assertEqual(load_pressure_values(csv_path), [3.0, 5.0])


if __name__ == "__main__":
    unittest.main()
