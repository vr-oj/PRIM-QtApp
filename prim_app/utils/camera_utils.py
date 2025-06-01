import os
import json
import cv2
import logging

log = logging.getLogger(__name__)

# Paths to camera report JSONs (adjust if needed)
CAMERA_REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "camera_reports")
KNOWN_CAMERAS = {
    "DMK 33UX250": "DMK 33UX250_camera_report.json",
    "DMK 33UP5000": "DMK 33UP5000_camera_report.json",
}


def _load_camera_profile(model_name):
    try:
        filename = KNOWN_CAMERAS.get(model_name)
        if not filename:
            log.warning(f"No known camera report for: {model_name}")
            return None
        path = os.path.join(CAMERA_REPORTS_DIR, filename)
        with open(path, "r") as f:
            data = json.load(f)
        profile = {
            "safe_fallback_resolution": tuple(
                data.get("safe_fallback_resolution", [1280, 720])
            ),
            "default_fps": data.get("default_fps", 10),
            "max_resolution": tuple(data.get("max_resolution", [1920, 1080])),
            "max_fps": data.get("max_fps", 60),
        }
        return profile
    except Exception as e:
        log.error(f"Failed to load camera profile for {model_name}: {e}")
        return None


def detect_connected_camera():
    try:
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cap.isOpened():
            log.warning("OpenCV could not open camera at index 0.")
            return None, {}

        # Try to infer resolution
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        # Use resolution heuristic to identify
        if (width, height) == (1920, 1200):
            model = "DMK 33UX250"
        elif (width, height) == (2592, 2048):
            model = "DMK 33UP5000"
        else:
            model = None

        profile = _load_camera_profile(model) if model else {}
        return model, profile or {}

    except Exception as e:
        log.error(f"Error detecting camera: {e}")
        return None, {}
