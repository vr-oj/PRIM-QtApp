# PRIM-QTAPP/prim_app/prim_app.py
import sys
import os
import re
import traceback
import logging
from PyQt5.QtWidgets import QApplication, QMessageBox, QStyleFactory
from PyQt5.QtCore import Qt, QCoreApplication, QLoggingCategory
from PyQt5.QtGui import QIcon

# Move module_log initialization earlier
module_log = logging.getLogger("prim_app.setup")
if not module_log.handlers:  # Ensure basic handler if not configured by main logger yet
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

    SETTING_CTI_PATH = "cti_path"
    # Use the now defined module_log
    module_log.warning("utils.app_settings not found. CTI persistence will not work.")

# === IC4 library import & availability flag ===
try:
    import imagingcontrol4 as ic4

    IC4_AVAILABLE = True
    ic4_library_module = ic4
    # Use the now defined module_log
    module_log.info(
        "imagingcontrol4 module imported successfully"
    )  # This is the original line 33
except ImportError:
    IC4_AVAILABLE = False
    ic4_library_module = None
    # Use the now defined module_log
    module_log.error(
        "Could not import imagingcontrol4 — camera functionality will be disabled."
    )


# === IC4 Initialization Flags and Module Reference ===
IC4_AVAILABLE = False  # This line seems redundant given the try/except block above setting it. Consider reviewing.
IC4_LIBRARY_INITIALIZED = False
IC4_GENTL_SYSTEM_CONFIGURED = False
ic4_library_module = None  # This line also seems redundant.

module_log = logging.getLogger("prim_app.setup")
if not module_log.handlers:  # Ensure basic handler if not configured by main logger yet
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] - %(message)s"
    )
    handler.setFormatter(formatter)
    module_log.addHandler(handler)
    module_log.setLevel(logging.INFO)


def initialize_ic4_with_cti(cti_path: str):
    """
    Initialize IC4 by handing the CTI path directly to Library.init(),
    then mark IC4_AVAILABLE=True so MainWindow will enable camera features.
    """
    # 1) Persist your choice so on next launch you don’t get prompted again
    save_app_setting(SETTING_CTI_PATH, cti_path)

    # 2) Call Library.init with the CTI path
    try:
        # In 1.3.x this will load that single CTI file (no need for gentl.System calls)
        ic4.Library.init(cti_path)
        log.info(f"IC4.Library.init({cti_path!r}) succeeded")
    except Exception as e:
        log.error(f"Failed to init IC4 with CTI {cti_path!r}: {e}")
        # bubble up so you still get the dialog
        raise

    # 3) Flip your flags so MainWindow knows everything is good
    global IC4_LIBRARY_INITIALIZED, IC4_GENTL_SYSTEM_CONFIGURED, IC4_AVAILABLE
    IC4_LIBRARY_INITIALIZED = True
    IC4_GENTL_SYSTEM_CONFIGURED = (
        True  # we don’t need gentl.System anymore, but you can keep this flag
    )
    IC4_AVAILABLE = True


# --- Combined Check ---
def is_ic4_fully_initialized():
    """Checks if both the IC4 library is init'd AND GenTL is configured with a CTI."""
    return IC4_LIBRARY_INITIALIZED and IC4_GENTL_SYSTEM_CONFIGURED


# Configure logging from utils.config if available
try:
    from utils.config import (
        APP_NAME as CONFIG_APP_NAME,
        LOG_LEVEL,
        APP_VERSION as CONFIG_APP_VERSION,
    )

    # Use a different name to avoid conflict with module-level APP_NAME if this file is also an entry point
    # However, this prim_app.py is mostly a module now.
    APP_NAME = CONFIG_APP_NAME  # Assign from config

    root_logger = logging.getLogger()  # Get root logger
    # Clear existing handlers from root logger only if necessary, be cautious
    # for h in root_logger.handlers[:]:
    #     root_logger.removeHandler(h)
    #     h.close()

    log_level_from_config = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    # Set basicConfig for the whole application if this is the first point of configuration
    # The force=True might be problematic if other modules configure logging earlier.
    # It's generally better to get the root logger and add handlers/set level.
    logging.basicConfig(
        level=log_level_from_config,
        format="%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] %(threadName)s - %(message)s",
        force=True,  # This will remove and re-add handlers. Use with caution.
    )
    log = logging.getLogger(__name__)  # Logger for this module
    log.info(f"Logging configured from utils.config: Level {LOG_LEVEL.upper()}")
except ImportError:
    APP_NAME = "PRIM Application (Default)"  # Default if config not found
    CONFIG_APP_VERSION = "1.0d"
    log = logging.getLogger(__name__)  # Logger for this module
    if not log.handlers:  # Configure only if no handlers are set up yet
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] %(threadName)s - %(message)s",
        )
    log.warning(
        "utils.config not found or APP_NAME not in it: using default logging and app name."
    )


# Suppress verbose logs from other libraries
logging.getLogger("matplotlib").setLevel(logging.WARNING)
QLoggingCategory.setFilterRules("qt.qss.styleSheet=false")  # For Qt


def load_processed_qss(path):
    """Load (and substitute variables in) a QSS file."""
    var_re = re.compile(r"@([A-Za-z0-9_]+):\s*(#[0-9A-Fa-f]{3,8});")
    vars_map = {}
    lines = []
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
    except FileNotFoundError:
        log.error(f"QSS file not found: {path}")
        return ""
    except Exception as e:
        log.error(f"Error loading QSS {path}: {e}")
        return ""


def _cleanup_ic4():
    """Gracefully exit the IC4 library on application quit."""
    global IC4_LIBRARY_INITIALIZED, IC4_GENTL_SYSTEM_CONFIGURED, ic4_library_module
    # Only attempt exit if Library.init() was called.
    if IC4_LIBRARY_INITIALIZED and ic4_library_module:
        try:
            log.info("Exiting IC4 library...")
            ic4_library_module.Library.exit()
            IC4_LIBRARY_INITIALIZED = False
            IC4_GENTL_SYSTEM_CONFIGURED = False  # Reset this as well
            log.info("IC4 library exited.")
        except RuntimeError as e:  # Catch specific IC4 runtime errors on exit
            log.warning(f"IC4 library exit runtime error: {e}")
        except Exception as e:
            log.error(f"Error during IC4 library exit: {e}")
    else:
        log.info(
            "IC4 library not initialized or module not available: skipping cleanup."
        )


def attempt_saved_ic4_init():
    """Attempts to initialize IC4 with a saved CTI path from app_settings."""
    # Flags will be set by initialize_ic4_with_cti
    if not APP_SETTINGS_AVAILABLE:
        log.warning("App settings module not available. Cannot attempt saved IC4 init.")
        return

    saved_cti_path = load_app_setting(SETTING_CTI_PATH)
    if saved_cti_path and os.path.exists(saved_cti_path):
        module_log.info(
            f"Found saved CTI path: {saved_cti_path}. Attempting initialization."
        )
        try:
            initialize_ic4_with_cti(saved_cti_path)
            if is_ic4_fully_initialized():
                module_log.info(
                    f"Successfully initialized IC4 with saved CTI: {saved_cti_path}"
                )
            else:
                module_log.warning(
                    f"Failed to fully initialize with saved CTI: {saved_cti_path}. User may be prompted."
                )
        except Exception as e:
            module_log.error(
                f"Error during saved CTI initialization for {saved_cti_path}: {e}. User may be prompted."
            )
    else:
        if saved_cti_path:
            module_log.warning(
                f"Saved CTI path '{saved_cti_path}' not found. User will be prompted by MainWindow."
            )
        else:
            module_log.info(
                "No saved CTI path found. User will be prompted by MainWindow."
            )


def main_app_entry():
    # Logging should be configured by now (either from config or defaults)
    log.info(
        f"Starting main_app_entry. Initial flags: IC4_AVAILABLE={IC4_AVAILABLE}, "
        f"IC4_LIBRARY_INITIALIZED={IC4_LIBRARY_INITIALIZED}, IC4_GENTL_SYSTEM_CONFIGURED={IC4_GENTL_SYSTEM_CONFIGURED}"
    )

    attempt_saved_ic4_init()
    log.info(
        f"After attempt_saved_ic4_init: IC4_AVAILABLE={IC4_AVAILABLE}, "
        f"IC4_LIBRARY_INITIALIZED={IC4_LIBRARY_INITIALIZED}, IC4_GENTL_SYSTEM_CONFIGURED={IC4_GENTL_SYSTEM_CONFIGURED}"
    )

    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    # Correct icon path assuming 'ui/icons' is relative to this file's parent if prim_app.py is top-level,
    # or relative to this file if it's in a subdirectory.
    # If prim_app.py is in 'prim_app' directory, and icons in 'prim_app/ui/icons':
    icon_path_base = os.path.join(base_dir, "ui", "icons")
    ico = os.path.join(icon_path_base, "PRIM.ico")
    png = os.path.join(icon_path_base, "PRIM.png")

    icon = QIcon()
    if os.path.exists(ico):
        icon.addFile(ico)
    elif os.path.exists(png):
        icon.addFile(png)
    else:
        log.warning(f"Application icon not found at {ico} or {png}")
    if not icon.isNull():
        app.setWindowIcon(icon)

    # MainWindow will handle specific CTI prompts.
    # This generic warning is if the imagingcontrol4 module itself is missing.
    if not IC4_AVAILABLE and not os.environ.get("PRIM_APP_TESTING_NO_IC4"):
        QMessageBox.critical(
            None,
            f"{APP_NAME} - Camera SDK Missing",
            "The 'imagingcontrol4' Python module was not found. Camera functionality will be disabled.\n"
            "Please install it (e.g., 'pip install imagingcontrol4') and ensure it matches your camera's SDK version.",
        )

    def custom_exception_handler(exc_type, value, tb):
        msg = "".join(traceback.format_exception(exc_type, value, tb))
        log.critical(f"UNCAUGHT EXCEPTION:\n{msg}")
        dlg = QMessageBox(
            QMessageBox.Critical,
            f"{APP_NAME} - Critical Error",
            "An unhandled error occurred. Please check the logs for more details.",
            QMessageBox.Ok,
        )
        dlg.setDetailedText(msg)
        dlg.exec_()

    sys.excepthook = custom_exception_handler

    style_path = os.path.join(
        base_dir, "style.qss"
    )  # Assuming style.qss is in the same dir as prim_app.py
    if os.path.exists(style_path):
        qss = load_processed_qss(style_path)
        if qss:
            app.setStyleSheet(qss)
            log.info(f"Applied stylesheet: {style_path}")
        else:
            app.setStyle(QStyleFactory.create("Fusion"))
            log.warning("Failed to apply QSS: using Fusion.")
    else:
        app.setStyle(QStyleFactory.create("Fusion"))
        log.info("No style.qss found: using Fusion.")

    from main_window import MainWindow  # Import here after initializations

    main_win = MainWindow()
    # Use CONFIG_APP_VERSION which is expected to be from utils.config
    version_to_display = (
        CONFIG_APP_VERSION if "CONFIG_APP_VERSION" in globals() else "1.0"
    )
    main_win.setWindowTitle(f"{APP_NAME} v{version_to_display}")
    main_win.showMaximized()
    log.info("Main window shown.")

    # Connect cleanup only if Library.init() was ever successfully called.
    if IC4_LIBRARY_INITIALIZED:  # Check if Library.init() was ever successful
        app.aboutToQuit.connect(_cleanup_ic4)
        log.info("IC4 cleanup function connected to app.aboutToQuit.")
    else:
        log.info(
            "IC4 library was not successfully initialized this session: skipping cleanup connect."
        )

    code = app.exec_()
    log.info(f"Exiting with code {code}.")
    sys.exit(code)


if __name__ == "__main__":
    # Basic logging for the launcher itself, before the main config kicks in
    launcher_log = logging.getLogger("prim_app_launcher")
    if not launcher_log.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        )
    launcher_log.info(
        f"Launching prim_app.py. Initial global flags: IC4_LIBRARY_INITIALIZED={IC4_LIBRARY_INITIALIZED}, IC4_GENTL_SYSTEM_CONFIGURED={IC4_GENTL_SYSTEM_CONFIGURED}"
    )
    main_app_entry()
