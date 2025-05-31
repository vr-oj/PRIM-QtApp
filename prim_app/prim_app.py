# PRIM-QTAPP/prim_app/prim_app.py
import sys
import os
import re
import traceback
import logging
from PyQt5.QtWidgets import QApplication, QMessageBox, QStyleFactory
from PyQt5.QtCore import Qt, QCoreApplication, QLoggingCategory
from PyQt5.QtGui import QIcon, QSurfaceFormat  # ADDED QSurfaceFormat

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
    from utils.app_settings import load_app_setting, save_app_setting, SETTING_CTI_PATH

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
    # Initial log before any major operations
    log.info(
        f"Application starting... Name: {APP_NAME}, Version: {CONFIG_APP_VERSION if 'CONFIG_APP_VERSION' in globals() else 'N/A'}"
    )

    # --- SET DEFAULT OPENGL SURFACE FORMAT ---
    # This should be done BEFORE the QApplication instance is created.
    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.OpenGL)  # Ensure OpenGL is the renderable type
    fmt.setProfile(QSurfaceFormat.CoreProfile)  # Request Core Profile
    fmt.setVersion(3, 3)  # Request OpenGL 3.3
    # fmt.setOption(QSurfaceFormat.DebugContext, True) # Optional: for more verbose GL debugging from drivers
    QSurfaceFormat.setDefaultFormat(fmt)
    log.info(
        "Attempted to set default QSurfaceFormat to OpenGL 3.3 Core Profile globally."
    )
    # --- END SET DEFAULT OPENGL FORMAT ---

    # High DPI scaling attributes (Qt specific)
    if hasattr(Qt, "AA_EnableHighDpiScaling"):  # For Qt 5.6+
        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):  # For Qt 5.0+
        QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    # Log the actual default format AFTER QApplication is created, as it might influence context creation
    # This helps confirm if the setDefaultFormat call was effective.
    actual_default_fmt = QSurfaceFormat.defaultFormat()
    log.info(
        f"Actual default QSurfaceFormat after QApplication init: Version {actual_default_fmt.majorVersion()}.{actual_default_fmt.minorVersion()}, Profile: {'Core' if actual_default_fmt.profile() == QSurfaceFormat.CoreProfile else 'Compatibility' if actual_default_fmt.profile() == QSurfaceFormat.CompatibilityProfile else 'NoProfile'}"
    )

    # Application Icon
    base_dir = os.path.dirname(os.path.abspath(__file__))
    icon_dir = os.path.join(base_dir, "ui", "icons")
    # Fallback if running from a different structure (e.g. project root for tests)
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
        # Format the traceback
        error_message = "".join(traceback.format_exception(exc_type, value, tb))
        log.critical(f"UNHANDLED PYTHON EXCEPTION CAUGHT:\n{error_message}")

        # Create and show a QMessageBox
        # Ensure a QApplication instance exists for QMessageBox, which it should here.
        error_dialog = QMessageBox(
            QMessageBox.Critical,  # Icon
            f"{APP_NAME} - Critical Application Error",  # Title
            "An unhandled error occurred, and the application might be unstable.\nPlease check the logs for details.",  # Main text
            QMessageBox.Ok,  # Buttons
        )
        error_dialog.setDetailedText(error_message)  # Allow user to see full traceback
        error_dialog.exec_()  # Show the dialog
        # Optionally, decide if the app should exit here, e.g., by calling QApplication.quit() or sys.exit()
        # For now, it allows the app to continue if possible, but it might be unstable.

    sys.excepthook = custom_exception_handler

    # Load application stylesheet
    style_path = os.path.join(
        base_dir, "style.qss"
    )  # Assuming style.qss is in the same dir as prim_app.py
    if os.path.exists(style_path):
        qss_content = load_processed_qss(style_path)
        if qss_content:
            app.setStyleSheet(qss_content)
            log.info(f"Applied stylesheet from: {style_path}")
        else:
            log.warning(
                f"Stylesheet {style_path} was empty or failed to load. Using default style."
            )
            app.setStyle(QStyleFactory.create("Fusion"))  # Fallback style
    else:
        log.info("No stylesheet (style.qss) found. Using default style 'Fusion'.")
        app.setStyle(QStyleFactory.create("Fusion"))  # Default style if no QSS

    # Import MainWindow after setting up global configurations like QSurfaceFormat
    from main_window import MainWindow

    main_win = MainWindow()
    # Determine version string safely
    app_display_version = (
        CONFIG_APP_VERSION
        if "CONFIG_APP_VERSION" in globals() and CONFIG_APP_VERSION
        else "Unknown"
    )
    main_win.setWindowTitle(f"{APP_NAME} v{app_display_version}")
    main_win.show()  # showMaximized() can be called from MainWindow's init or after show()

    exit_code = app.exec_()
    log.info(f"Application event loop finished with exit code: {exit_code}")
    sys.exit(exit_code)


if __name__ == "__main__":
    # This initial logger is just for the launcher part, before full config.
    launcher_log = logging.getLogger("prim_app_launcher")
    if (
        not launcher_log.handlers
    ):  # Avoid adding handlers multiple times if script is re-run in some envs
        logging.basicConfig(  # Basic config for very early messages
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - [%(name)s] - %(message)s",
        )
    main_app_entry()
