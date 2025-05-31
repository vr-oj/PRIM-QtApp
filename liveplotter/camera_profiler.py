# camera_profiler.py
import json
import os

PROFILE_PATH = os.path.join(os.path.dirname(__file__), "camera_profile.json")


def save_camera_profile(model_name: str, resolution: str):
    try:
        with open(PROFILE_PATH, "w") as f:
            json.dump({"model": model_name, "resolution": resolution}, f)
    except Exception as e:
        print(f"Failed to save camera profile: {e}")


def load_camera_profile():
    if not os.path.exists(PROFILE_PATH):
        return None, None
    try:
        with open(PROFILE_PATH, "r") as f:
            data = json.load(f)
            return data.get("model"), data.get("resolution")
    except Exception as e:
        print(f"Failed to load camera profile: {e}")
        return None, None
