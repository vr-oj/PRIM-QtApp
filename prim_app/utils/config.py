# PRIM-QTAPP/prim_app/utils/config.py
import os
from pathlib import Path
from PyQt5.QtCore import QStandardPaths, QDir

# Base folders
DOCUMENTS_DIR = os.path.join(os.path.expanduser("~"), "Documents")
PRIM_RESULTS_DIR = os.path.join(DOCUMENTS_DIR, "PRIMAcquisition Results")

# Ensure results directory exists
Path(PRIM_RESULTS_DIR).mkdir(parents=True, exist_ok=True)

# ─── Recording settings ─────────────────────────────────────────────────────────
DEFAULT_VIDEO_EXTENSION = "avi"  # Default format for µManager recorder
DEFAULT_VIDEO_CODEC = "MJPG"  # Codec used only if extension == "avi"
SUPPORTED_FORMATS = ["avi", "tif"]  # Dropdown options for recording format
DEFAULT_FPS = 20  # Camera frames per second target
DEFAULT_CAMERA_INDEX = 0  # Default device index for OpenCV

# Frame size fallback (actual size queried from camera at runtime)
DEFAULT_FRAME_SIZE = (640, 480)  # (width, height)

# ─── Serial communication ────────────────────────────────────────────────────────
DEFAULT_SERIAL_BAUD_RATE = 115200
SERIAL_COMMAND_TERMINATOR = b"\n"  # Arduino uses Serial.println()

# ─── Application info ───────────────────────────────────────────────────────────
APP_NAME = "PRIMAcquisition"
APP_VERSION = "1.0"
ABOUT_TEXT = f"""
<strong>{APP_NAME} v{APP_VERSION}</strong>
<p>Passive Data Logger and Viewer for the PRIM system.</p>
<p>This application displays live camera feed and pressure data from the PRIM device,
and allows recording of this data.</p>
<p>Experiment control (start/stop) is managed via the PRIM device's physical controls.</p>
"""

# ─── Logging ────────────────────────────────────────────────────────────────────
LOG_LEVEL = "DEBUG"  # DEBUG, INFO, WARNING, ERROR

# ─── Plotting ──────────────────────────────────────────────────────────────────
PLOT_MAX_POINTS = 1000  # Max points to keep in live plot
PLOT_DEFAULT_Y_MIN = -5
PLOT_DEFAULT_Y_MAX = 30  # Typical pressure range in mmHg

# ─── Camera profiles / Application config directory ─────────────────────────────
# User-writable directory for storing camera profiles
APP_CONFIG_DIR = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
CAMERA_PROFILES_DIR = os.path.join(APP_CONFIG_DIR, "camera_profiles")

# Ensure camera profiles directory exists
QDir().mkpath(CAMERA_PROFILES_DIR)

# ─── Camera resolutions placeholder (populated at runtime) ─────────────────────
AVAILABLE_RESOLUTIONS = [
    "640x480",
    "800x600",
    "1280x720",
    "1920x1080",
]
