# PRIM-QTAPP/prim_app/prim_app.py

import sys
import os
import re
import traceback
import logging
import imagingcontrol4 as ic4  # <-- Added for IC4 initialization

from PyQt5.QtWidgets import QApplication, QMessageBox, QStyleFactory
from PyQt5.QtCore import Qt, QCoreApplication, QLoggingCategory
from PyQt5.QtGui import QIcon, QSurfaceFormat
from utils.config import APP_NAME, APP_VERSION as CONFIG_APP_VERSION
import matplotlib

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] - %(message)s",
)

# Suppress matplotlib font_manager DEBUG logs
logging.getLogger("matplotlib").setLevel(logging.INFO)
logging.getLogger("matplotlib.font_manager").setLevel(logging.WARNING)
logging.getLogger("fontTools").setLevel(logging.WARNING)

log = logging.getLogger(__name__)

# === Module-level logger for setup ===
module_log = logging.getLogger("prim_app.setup")
if not module_log.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] - %(message)s"
    )
    handler.setFormatter(formatter)
    module_log.addHandler(handler)
    module_log.setLevel(logging.INFO)

# === App Settings Import ===
try:
    from utils.app_settings import load_app_setting, save_app_setting

    APP_SETTINGS_AVAILABLE = True
except ImportError:
    APP_SETTINGS_AVAILABLE = False

    def load_app_setting(key, default=None):
        return default

    def save_app_setting(key, value):
        pass

    SETTING_CTI_PATH = "cti_path"
    module_log.warning("utils.app_settings not found. CTI persistence will not work.")


def load_processed_qss(path):
    var_re = re.compile(r"@([A-Za-z0-9_]+):\s*(#[0-9A-Fa-f]{3,8});")
    vars_map, lines = {}, []
    try:
        with open(path, "r") as f:
            for line in f:
                m = var_re.match(line)
                if m:
                    vars_map[m.group(1)] = m.group(2)
                else:
                    # Replace all defined variables in the current line
                    for name, val in vars_map.items():
                        line = line.replace(f"@{name}", val)
                    lines.append(line)
        return "".join(lines)
    except Exception as e:
        log.error(f"Error loading or processing QSS file {path}: {e}")
        return ""  # Return empty string on error


def main_app_entry():
    # --- SET DEFAULT OPENGL SURFACE FORMAT ---
    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.OpenGL)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setVersion(3, 3)
    QSurfaceFormat.setDefaultFormat(fmt)
    log.info(
        "Attempted to set default QSurfaceFormat to OpenGL 3.3 Core Profile globally."
    )
    # --- END SET DEFAULT OPENGL FORMAT ---

    # High DPI scaling attributes
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    # Create the QApplication
    app = QApplication(sys.argv)

    # Log the actual default QSurfaceFormat after QApplication created
    actual_default_fmt = QSurfaceFormat.defaultFormat()
    log.info(
        f"Actual default QSurfaceFormat after QApplication init: "
        f"Version {actual_default_fmt.majorVersion()}.{actual_default_fmt.minorVersion()}, "
        f"Profile: {('Core' if actual_default_fmt.profile() == QSurfaceFormat.CoreProfile else 'Compatibility' if actual_default_fmt.profile() == QSurfaceFormat.CompatibilityProfile else 'NoProfile')}"
    )

    # Application Icon
    base_dir = os.path.dirname(os.path.abspath(__file__))
    icon_dir = os.path.join(base_dir, "ui", "icons")
    if not os.path.isdir(icon_dir):
        alt_icon_dir = os.path.join(
            os.path.dirname(base_dir), "prim_app", "ui", "icons"
        )
        if os.path.isdir(alt_icon_dir):
            icon_dir = alt_icon_dir
        else:
            log.warning(
                f"Icon directory not found at expected paths: {icon_dir} or {alt_icon_dir}"
            )

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
        log.warning("Application icon file (PRIM.ico or PRIM.png) not found.")

    # Custom exception handler for unhandled Python exceptions
    def custom_exception_handler(exc_type, value, tb):
        error_message = "".join(traceback.format_exception(exc_type, value, tb))
        log.critical(f"UNHANDLED PYTHON EXCEPTION CAUGHT:\n{error_message}")

        error_dialog = QMessageBox(
            QMessageBox.Critical,
            f"{APP_NAME} - Critical Application Error",
            "An unhandled error occurred, and the application might be unstable.\nPlease check the logs for details.",
            QMessageBox.Ok,
        )
        error_dialog.setDetailedText(error_message)
        error_dialog.exec_()

    sys.excepthook = custom_exception_handler

    # Load application stylesheet
    style_path = os.path.join(base_dir, "style.qss")
    if os.path.exists(style_path):
        qss_content = load_processed_qss(style_path)
        if qss_content:
            app.setStyleSheet(qss_content)
            log.info(f"Applied stylesheet from: {style_path}")
        else:
            log.warning(
                f"Stylesheet {style_path} was empty or failed to load. Using default style."
            )
            app.setStyle(QStyleFactory.create("Fusion"))
    else:
        log.info("No stylesheet (style.qss) found. Using default style 'Fusion'.")
        app.setStyle(QStyleFactory.create("Fusion"))

    # === Initialize IC4 Library Once ===
    try:
        ic4.Library.init()
        log.info("IC4 Library initialized successfully.")
    except ic4.IC4Exception as e:
        log.critical(f"Could not initialize IC4: {e}")
        # Show a critical message box and exit early
        QMessageBox.critical(
            None,
            f"{APP_NAME} - Camera Initialization Error",
            f"Failed to initialize the IC4 library:\n{e}\n\n"
            "The application will now exit.",
        )
        sys.exit(1)

    # Import MainWindow after IC4 is initialized
    from main_window import MainWindow

    # Instantiate and show the main window
    main_win = MainWindow()
    app_display_version = CONFIG_APP_VERSION if CONFIG_APP_VERSION else "Unknown"
    main_win.setWindowTitle(f"{APP_NAME} v{app_display_version}")
    main_win.show()

    # Run the event loop
    exit_code = app.exec_()
    log.info(f"Application event loop finished with exit code: {exit_code}")

    # === Clean up IC4 Library on exit ===
    try:
        ic4.Library.close()
        log.info("IC4 Library closed cleanly.")
    except Exception as e_close:
        log.error(f"Error closing IC4 Library: {e_close}")

    sys.exit(exit_code)


if __name__ == "__main__":
    # Launcher logger
    launcher_log = logging.getLogger("prim_app_launcher")
    if not launcher_log.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - [%(name)s] - %(message)s",
        )
    main_app_entry()
