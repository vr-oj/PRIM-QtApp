import time, cv2
import serial.tools.list_ports


def list_serial_ports():
    return [(p.device, p.description) for p in serial.tools.list_ports.comports()]


def timestamped_filename(prefix, ext):
    ts = time.strftime("%Y%m%d-%H%M%S")
    return f"{prefix}_{ts}.{ext}"


def list_cameras(max_idx=5):
    cams = []
    for i in range(max_idx):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if cap.isOpened() and cap.read()[0]:
            cams.append(i)
        cap.release()
    return cams


# utils.py (append this at the bottom)
import json


def get_prim_settings_path():
    from pathlib import Path

    settings_dir = Path.home() / ".prim"
    settings_dir.mkdir(parents=True, exist_ok=True)
    return settings_dir / "prim_settings.json"


def load_prim_settings():
    path = get_prim_settings_path()
    if path.exists():
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_prim_settings(data: dict):
    path = get_prim_settings_path()
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Warning: Failed to save prim settings: {e}")
