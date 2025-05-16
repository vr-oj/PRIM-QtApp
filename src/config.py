import os

# Base folder for all trial outputs
DOCUMENTS_DIR = os.path.join(os.path.expanduser("~"), "Documents")
PRIM_RESULTS_DIR = os.path.join(DOCUMENTS_DIR, "PRIMalyze Results")


# Recording settings
DEFAULT_VIDEO_CODEC = "MJPG"
DEFAULT_VIDEO_EXTENSION = "avi"
DEFAULT_FPS = 20  # Adjusted based on typical Arduino sampling if it's around 10Hz (20-30fps is fine)
DEFAULT_CAMERA_INDEX = 0  # Or your preferred default camera
DEFAULT_FRAME_SIZE = (
    640,
    480,
)  # Tuple (width, height) - This should ideally be set from camera

# Serial communication settings
DEFAULT_SERIAL_BAUD_RATE = 115200
SERIAL_COMMAND_TERMINATOR = b"\n"  # Arduino uses Serial.println()

# Application Information
APP_VERSION = "1.0"
APP_NAME = "PRIMalyzer"
ABOUT_TEXT = f"""
<strong>{APP_NAME} v{APP_VERSION}</strong>
<p>Passive Data Logger and Viewer for the PRIM system.</p>
<p>This application displays live camera feed and pressure data from the PRIM device,
and allows recording of this data.</p>
<p>Experiment control (start/stop) is managed via the PRIM device's physical controls.</p>
"""

# Logging configuration
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR

# Plotting
PLOT_MAX_POINTS = 1000  # Max data points to keep on the live plot for performance
PLOT_DEFAULT_Y_MIN = 0
PLOT_DEFAULT_Y_MAX = 30  # Adjust based on typical pressure range in mmHg

# Camera settings (can be expanded)
AVAILABLE_RESOLUTIONS = [  # Example, should be dynamically populated
    "640x480",
    "800x600",
    "1280x720",
    "1920x1080",
    # Add more or detect from camera
]
