# File: prim_app/utils/config.py

import os
from pathlib import Path
from datetime import date
from PyQt5.QtCore import QStandardPaths, QDir

# ─── User’s Documents folder ───────────────────────────────────────────────────
DOCUMENTS_DIR = os.path.join(os.path.expanduser("~"), "Documents")

# ─── “Root” for all PRIMAcquisition recordings ─────────────────────────────────
PRIM_ROOT = os.path.join(DOCUMENTS_DIR, "PRIMAcquisition Results")
Path(PRIM_ROOT).mkdir(parents=True, exist_ok=True)

# ─── Legacy results folder (kept for compatibility, if needed) ─────────────────
PRIM_RESULTS_DIR = os.path.join(DOCUMENTS_DIR, "PRIMAcquisition Results")
Path(PRIM_RESULTS_DIR).mkdir(parents=True, exist_ok=True)

# ─── Recording settings ─────────────────────────────────────────────────────────
DEFAULT_VIDEO_EXTENSION = "tif"
DEFAULT_VIDEO_CODEC = None  # Not used when recording to TIFF
SUPPORTED_FORMATS = ["tif"]
DEFAULT_FPS = 10
DEFAULT_CAMERA_INDEX = 0  # Default device index

# Frame size fallback (actual size will be queried from camera at runtime)
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
<p>This application displays a live camera feed and pressure data from the PRIM device,
and allows recording of this data into a high‐resolution TIFF stack (with embedded metadata)
and a synchronized CSV log.</p>
<p>Experiment control (start/stop) can be triggered directly from this application.</p>
"""

# ─── Logging ────────────────────────────────────────────────────────────────────
LOG_LEVEL = "DEBUG"  # DEBUG, INFO, WARNING, ERROR

# ─── Plotting ──────────────────────────────────────────────────────────────────
PLOT_MAX_POINTS = 1000  # Max points to keep in live plot
PLOT_DEFAULT_Y_MIN = -5
PLOT_DEFAULT_Y_MAX = 30  # Typical pressure range in mmHg

# ─── Camera profiles / Application config directory ─────────────────────────────
# User‐writable directory for storing camera profiles
APP_CONFIG_DIR = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
CAMERA_PROFILES_DIR = os.path.join(APP_CONFIG_DIR, "camera_profiles")
QDir().mkpath(CAMERA_PROFILES_DIR)
