# File: prim_app/prim_app.py

import sys
import os
import re
import traceback
import logging
import imagingcontrol4 as ic4

from PyQt5.QtWidgets import QApplication, QMessageBox, QStyleFactory
from PyQt5.QtCore import Qt, QCoreApplication
from PyQt5.QtGui import QIcon, QSurfaceFormat, QPalette, QColor
from utils.config import APP_NAME, APP_VERSION as CONFIG_APP_VERSION

import matplotlib

logging.getLogger("matplotlib").setLevel(logging.INFO)
logging.getLogger("matplotlib.font_manager").setLevel(logging.WARNING)
logging.getLogger("fontTools").setLevel(logging.WARNING)

# ------------------------------
# Configure Python-level logging
# ------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] - %(message)s",
)
log = logging.getLogger(__name__)

# A separate module-level logger for setup steps
module_log = logging.getLogger("prim_app.setup")
if not module_log.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] - %(message)s"
    )
    handler.setFormatter(formatter)
    module_log.addHandler(handler)
    module_log.setLevel(logging.INFO)


# === load_app_setting / save_app_setting stubs if missing ===
try:
    from utils.app_settings import load_app_setting, save_app_setting

    APP_SETTINGS_AVAILABLE = True
except ImportError:
    APP_SETTINGS_AVAILABLE = False

    def load_app_setting(key, default=None):
        return default

    def save_app_setting(key, value):
        pass

    module_log.warning(
        "utils.app_settings not found. Persistent settings will not work."
    )


def apply_dark_theme(app):
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.Window, QColor(45, 45, 45))
    dark_palette.setColor(QPalette.WindowText, Qt.white)
    dark_palette.setColor(QPalette.Base, QColor(30, 30, 30))
    dark_palette.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
    dark_palette.setColor(QPalette.ToolTipBase, Qt.white)
    dark_palette.setColor(QPalette.ToolTipText, Qt.white)
    dark_palette.setColor(QPalette.Text, Qt.white)
    dark_palette.setColor(QPalette.Button, QColor(45, 45, 45))
    dark_palette.setColor(QPalette.ButtonText, Qt.white)
    dark_palette.setColor(QPalette.BrightText, Qt.red)
    dark_palette.setColor(QPalette.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setPalette(dark_palette)


def load_processed_qss(path):
    """
    If you use “@variable: #RRGGBB;” in your QSS, this helper expands them.
    Returns the final QSS string or "" on error.
    """
    var_re = re.compile(r"@([A-Za-z0-9_]+):\s*(#[0-9A-Fa-f]{3,8});")
    vars_map, lines = {}, []
    try:
        with open(path, "r") as f:
            for line in f:
                m = var_re.match(line)
                if m:
                    vars_map[m.group(1)] = m.group(2)
                else:
                    for name, val in vars_map.items():
                        line = line.replace(f"@{name}", val)
                    lines.append(line)
        return "".join(lines)
    except Exception as e:
        log.error(f"Error loading/processing QSS file {path}: {e}")
        return ""


def main_app_entry():
    # ─── Set Default OpenGL 3.3 Core Profile ─────────────────────────────
    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.OpenGL)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setVersion(3, 3)
    QSurfaceFormat.setDefaultFormat(fmt)
    log.info(
        "Attempted to set default QSurfaceFormat to OpenGL 3.3 Core Profile globally."
    )
    # ──────────────────────────────────────────────────────────────────────

    # Enable high-DPI scaling if available
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    # ─── Initialize IC4 globally so MainWindow can enumerate devices ─────────
    try:
        ic4.Library.init(
            api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR
        )
        log.info("Global IC4 Library.init() succeeded.")
    except Exception as e:
        log.error(f"Could not initialize IC4 in main thread: {e}")
        # You might still allow the UI to start (with an empty device list),
        # or choose to exit right here with sys.exit(1).

    # Create the QApplication
    app = QApplication(sys.argv)
    apply_dark_theme(app)

    # Log what OpenGL/QSurfaceFormat we actually got
    actual_fmt = QSurfaceFormat.defaultFormat()
    profile_str = (
        "Core"
        if actual_fmt.profile() == QSurfaceFormat.CoreProfile
        else (
            "Compatibility"
            if actual_fmt.profile() == QSurfaceFormat.CompatibilityProfile
            else "NoProfile"
        )
    )
    log.info(
        f"Actual default QSurfaceFormat after QApplication init: "
        f"Version {actual_fmt.majorVersion()}.{actual_fmt.minorVersion()}, Profile: {profile_str}"
    )

    # ─── Load & Apply App Icon ─────────────────────────────────────────────
    base_dir = os.path.dirname(os.path.abspath(__file__))
    icon_dir = os.path.join(base_dir, "ui", "icons")
    if not os.path.isdir(icon_dir):
        alt_icon_dir = os.path.join(
            os.path.dirname(base_dir), "prim_app", "ui", "icons"
        )
        if os.path.isdir(alt_icon_dir):
            icon_dir = alt_icon_dir
        else:
            log.warning(f"Icon directory not found in {icon_dir} or {alt_icon_dir}")

    ico_path = os.path.join(icon_dir, "PRIM.ico")
    png_path = os.path.join(icon_dir, "PRIM.png")
    app_icon = QIcon()
    if os.path.exists(ico_path):
        app_icon.addFile(ico_path)
    elif os.path.exists(png_path):
        app_icon.addFile(png_path)

    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    else:
        log.warning("No application icon file (PRIM.ico or PRIM.png) found.")

    # ─── Install a Custom Exception Hook for Unhandled Errors ─────────────
    def custom_exception_handler(exc_type, value, tb):
        err_msg = "".join(traceback.format_exception(exc_type, value, tb))
        log.critical(f"UNHANDLED PYTHON EXCEPTION:\n{err_msg}")

        dlg = QMessageBox(
            QMessageBox.Critical,
            f"{APP_NAME} - Critical Error",
            "An unexpected error occurred. The application may be unstable.\n"
            "Check the logs for details.",
            QMessageBox.Ok,
        )
        dlg.setDetailedText(err_msg)
        dlg.exec_()

    sys.excepthook = custom_exception_handler

    # ─── Load Application QSS (if present) ────────────────────────────────
    style_path = os.path.join(base_dir, "style.qss")
    if os.path.exists(style_path):
        qss = load_processed_qss(style_path)
        if qss:
            app.setStyleSheet(qss)
            log.info(f"Applied stylesheet from: {style_path}")
        else:
            log.warning(f"Stylesheet was empty or failed to load: {style_path}")
            app.setStyle(QStyleFactory.create("Fusion"))
    else:
        log.info("No style.qss found. Using default 'Fusion' style.")
        app.setStyle(QStyleFactory.create("Fusion"))

    # ─── Import & Launch MainWindow ───────────────────────────────────────
    from main_window import MainWindow

    main_win = MainWindow()
    display_version = CONFIG_APP_VERSION or "Unknown"
    main_win.setWindowTitle(f"{APP_NAME} v{display_version}")
    main_win.show()

    exit_code = app.exec_()
    log.info(f"Application event loop ended with exit code {exit_code}.")

    # ─── Clean up IC4 when the app is closing ─────────────────────────────
    try:
        ic4.Library.exit()
        log.info("Global IC4 Library.exit() called.")
    except Exception:
        pass

    sys.exit(exit_code)


if __name__ == "__main__":
    main_app_entry()
