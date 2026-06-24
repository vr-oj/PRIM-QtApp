import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prim_app"))

from utils.recording_settings import (
    CAPTURE_SETTING_OPTIONS,
    build_recording_settings,
    capture_setting_code,
    format_prim_command,
    frame_interval_ms_from_fps,
    should_capture_tiff_frame,
)


class RecordingSettingsTests(unittest.TestCase):
    def test_frame_interval_rounds_up(self):
        self.assertEqual(frame_interval_ms_from_fps(10), 100)
        self.assertEqual(frame_interval_ms_from_fps(9), 112)
        self.assertEqual(frame_interval_ms_from_fps(1), 1000)

    def test_capture_labels_map_to_expected_codes(self):
        expected = {
            "None": 0,
            "Every": 1,
            "1 in 5": 5,
            "1 in 10": 10,
            "1 in 15": 15,
            "1 in 20": 20,
            "1 in 25": 25,
            "1 in 30": 30,
        }
        self.assertEqual(
            dict((label, code) for code, label in CAPTURE_SETTING_OPTIONS),
            expected,
        )
        for label, code in expected.items():
            self.assertEqual(capture_setting_code(label), code)

    def test_build_recording_settings(self):
        settings = build_recording_settings(9, 10)
        self.assertEqual(settings.recording_fps, 9.0)
        self.assertEqual(settings.frame_interval_ms, 112)
        self.assertEqual(settings.capture_setting_code, 10)
        self.assertEqual(settings.capture_setting_label, "1 in 10")
        self.assertTrue(settings.record_video)

        csv_only_settings = build_recording_settings(10, 0)
        self.assertFalse(csv_only_settings.record_video)

    def test_format_prim_command(self):
        self.assertEqual(format_prim_command("G", 100, 1), "<G, 100, 1>")
        self.assertEqual(format_prim_command("s", 112, 10), "<S, 112, 10>")
        self.assertEqual(format_prim_command("Z", 1000, 0), "<Z, 1000, 0>")

    def test_old_menu_index_values_are_rejected(self):
        with self.assertRaises(ValueError):
            build_recording_settings(9, 3)
        with self.assertRaises(ValueError):
            format_prim_command("G", 100, 3)

    def test_should_capture_tiff_frame(self):
        self.assertFalse(should_capture_tiff_frame(1, 0))
        self.assertTrue(should_capture_tiff_frame(1, 1))
        self.assertTrue(should_capture_tiff_frame(2, 1))
        self.assertFalse(should_capture_tiff_frame(9, 10))
        self.assertTrue(should_capture_tiff_frame(10, 10))
        self.assertTrue(should_capture_tiff_frame(20, 10))


if __name__ == "__main__":
    unittest.main()
