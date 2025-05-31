# app_settings.py
import os
import json

SETTINGS_FILENAME = "prim_settings.json"
SETTINGS_PATH = os.path.join(
    os.path.expanduser("~"), "AppData", "Local", SETTINGS_FILENAME
)


def load_app_setting(key: str, default=None):
    if not os.path.exists(SETTINGS_PATH):
        return default
    try:
        with open(SETTINGS_PATH, "r") as f:
            data = json.load(f)
            return data.get(key, default)
    except Exception:
        return default


def save_app_setting(key: str, value):
    try:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r") as f:
                data = json.load(f)
        else:
            data = {}
        data[key] = value
        with open(SETTINGS_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving setting {key}: {e}")
