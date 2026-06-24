import math
from dataclasses import dataclass


CAPTURE_SETTING_OPTIONS = (
    (0, "None"),
    (1, "Every"),
    (5, "1 in 5"),
    (10, "1 in 10"),
    (15, "1 in 15"),
    (20, "1 in 20"),
    (25, "1 in 25"),
    (30, "1 in 30"),
)

DEFAULT_CAPTURE_SETTING_CODE = 1

_CAPTURE_LABEL_BY_CODE = dict(CAPTURE_SETTING_OPTIONS)
_CAPTURE_CODE_BY_LABEL = {
    label: code for code, label in CAPTURE_SETTING_OPTIONS
}


@dataclass(frozen=True)
class RecordingSettings:
    recording_fps: float
    frame_interval_ms: int
    capture_setting_code: int
    capture_setting_label: str
    record_video: bool


def frame_interval_ms_from_fps(fps):
    """Return the integer Arduino frame delay for a requested FPS."""
    fps = float(fps)
    if fps <= 0:
        raise ValueError("FPS must be greater than zero.")
    return int(math.ceil(1000.0 / fps))


def capture_setting_label(code):
    code = int(code)
    if code not in _CAPTURE_LABEL_BY_CODE:
        raise ValueError(f"Unknown capture setting value: {code}.")
    return _CAPTURE_LABEL_BY_CODE[code]


def capture_setting_code(label):
    if label not in _CAPTURE_CODE_BY_LABEL:
        raise ValueError(f"Unknown capture setting label: {label}")
    return _CAPTURE_CODE_BY_LABEL[label]


def build_recording_settings(fps, capture_code=DEFAULT_CAPTURE_SETTING_CODE):
    code = int(capture_code)
    label = capture_setting_label(code)
    return RecordingSettings(
        recording_fps=float(fps),
        frame_interval_ms=frame_interval_ms_from_fps(fps),
        capture_setting_code=code,
        capture_setting_label=label,
        record_video=code != 0,
    )


def should_capture_tiff_frame(sample_number, capture_setting):
    """Return whether this 1-based serial sample should get a TIFF frame."""
    sample_number = int(sample_number)
    capture_setting = int(capture_setting)
    if sample_number <= 0:
        raise ValueError("Sample number must be greater than zero.")
    if capture_setting == 0:
        return False
    if capture_setting not in _CAPTURE_LABEL_BY_CODE:
        raise ValueError(f"Unknown capture setting value: {capture_setting}.")
    return sample_number % capture_setting == 0


def format_prim_command(command_char, frame_interval_ms, capture_setting):
    command_char = str(command_char).strip().upper()
    if command_char not in {"G", "S", "Z"}:
        raise ValueError(f"Unsupported PRIM command: {command_char}")

    frame_interval_ms = int(frame_interval_ms)
    capture_setting = int(capture_setting)
    if frame_interval_ms <= 0:
        raise ValueError("Frame interval must be greater than zero.")
    if capture_setting not in _CAPTURE_LABEL_BY_CODE:
        raise ValueError(
            f"Unknown capture setting value: {capture_setting}."
        )

    return f"<{command_char}, {frame_interval_ms}, {capture_setting}>"
