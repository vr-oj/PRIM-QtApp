# PRIM-QTAPP/prim_app/prim_app.py
import sys
import os
import re
import traceback
import logging
from PyQt5.QtWidgets import QApplication, QMessageBox, QStyleFactory
from PyQt5.QtCore import Qt, QCoreApplication, QLoggingCategory
from PyQt5.QtGui import QIcon

# === App Settings Import ===
# Ensure utils.app_settings is created or integrated into utils.config
try:
    from utils.app_settings import load_app_setting, SETTING_CTI_PATH

    APP_SETTINGS_AVAILABLE = True
except ImportError:
    APP_SETTINGS_AVAILABLE = False

    # Fallback if app_settings isn't available, though it's crucial for the new logic
    def load_app_setting(key, default=None):
        return default

    SETTING_CTI_PATH = "cti_path"


# === IC4 Initialization Flags and Module Reference ===
IC4_AVAILABLE = False
IC4_INITIALIZED = False
ic4_library_module = None
_ic4_init_has_run_successfully_this_session = False  # Tracks if init() ever succeeded

module_log = logging.getLogger("prim_app.setup")
if not module_log.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] - %(message)s"
    )
    handler.setFormatter(formatter)
    module_log.addHandler(handler)
    module_log.setLevel(logging.INFO)


def _initialize_ic4_globally():
    """
    Internal: initialize the IC Imaging Control library without specifying a CTI.
    Generally, prefer using initialize_ic4_with_cti().
    """
    global IC4_AVAILABLE, IC4_INITIALIZED, ic4_library_module, _ic4_init_has_run_successfully_this_session

    if _ic4_init_has_run_successfully_this_session and IC4_INITIALIZED:
        module_log.debug("IC4 already initialized globally.")
        return

    module_log.info("Attempting generic IC4 global initialization...")
    try:
        if ic4_library_module is None:
            import imagingcontrol4 as ic4

            ic4_library_module = ic4
        IC4_AVAILABLE = True
        ic4_library_module.Library.init()
        IC4_INITIALIZED = True
        _ic4_init_has_run_successfully_this_session = True
        module_log.info("ic4.Library.init() succeeded globally.")
    except ImportError:
        IC4_AVAILABLE = False
        IC4_INITIALIZED = False
        module_log.warning("imagingcontrol4 module not found during generic init.")
    except Exception as e:
        IC4_INITIALIZED = False
        module_log.error(f"ic4.Library.init() failed globally: {e}")
    finally:
        module_log.info(
            f"Global IC4 flags: AVAILABLE={IC4_AVAILABLE}, INITIALIZED={IC4_INITIALIZED}"
        )


def initialize_ic4_with_cti(cti_path: str):
    """
    Load a GenTL producer (.cti) and initialize the IC4 library.
    Call this once the user has selected or the app has discovered a CTI file.
    """
    global IC4_AVAILABLE, IC4_INITIALIZED, ic4_library_module, _ic4_init_has_run_successfully_this_session
    module_log.info(f"Loading GenTL producer from CTI: {cti_path}")
    if not os.path.exists(cti_path):
        module_log.error(f"CTI file not found at path: {cti_path}")
        IC4_INITIALIZED = False  # Ensure it's false
        raise FileNotFoundError(f"CTI file not found: {cti_path}")

    try:
        if ic4_library_module is None:
            import imagingcontrol4 as ic4

            ic4_library_module = ic4
        # Load the CTI
        ic4_library_module.Library.loadGenTLProducer(cti_path)
        IC4_AVAILABLE = (
            True  # If loadGenTLProducer succeeds, the module is definitely available
        )
        module_log.info(f"Loaded CTI: {cti_path}")
        # Initialize the library
        ic4_library_module.Library.init()
        IC4_INITIALIZED = True
        _ic4_init_has_run_successfully_this_session = True
        module_log.info("IC4 Library.init() succeeded after CTI load.")
    except ImportError:
        IC4_AVAILABLE = False
        IC4_INITIALIZED = False
        module_log.error("imagingcontrol4 module not found when trying to load CTI.")
        raise  # Re-raise import error
    except Exception as e:
        IC4_INITIALIZED = False  # Explicitly set to False on failure
        module_log.error(f"Failed to initialize IC4 with CTI {cti_path}: {e}")
        raise  # Re-raise other exceptions


# Configure logging from utils.config if available
try:
    from utils.config import APP_NAME, LOG_LEVEL, APP_VERSION as CONFIG_APP_VERSION

    root_logger = logging.getLogger()
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
        h.close()

    log_level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] %(threadName)s - %(message)s",
        force=True,
    )
    log = logging.getLogger(__name__)
    log.info(f"Logging configured: {LOG_LEVEL.upper()}")
except ImportError:
    APP_NAME = "PRIM Application"
    CONFIG_APP_VERSION = "1.0"
    log = logging.getLogger(__name__)
    if not log.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] %(threadName)s - %(message)s",
            force=True,
        )
    log.warning("utils.config not found: using defaults.")

# Suppress verbose logs
logging.getLogger("matplotlib").setLevel(logging.WARNING)
QLoggingCategory.setFilterRules("qt.qss.styleSheet=false")


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
    global IC4_INITIALIZED, ic4_library_module
    if IC4_INITIALIZED and ic4_library_module:
        try:
            log.info("Exiting IC4 library...")
            ic4_library_module.Library.exit()
            IC4_INITIALIZED = False
            log.info("IC4 library exited.")
        except RuntimeError as e:
            log.warning(f"IC4 exit runtime error: {e}")
        except Exception as e:
            log.error(f"Error during IC4 exit: {e}")
    else:
        log.info("IC4 not initialized or module not available: skipping cleanup.")


def attempt_saved_ic4_init():
    """Attempts to initialize IC4 with a saved CTI path."""
    global IC4_INITIALIZED  # We will modify this global flag
    if not APP_SETTINGS_AVAILABLE:
        log.warning("App settings module not available. Cannot attempt saved IC4 init.")
        IC4_INITIALIZED = False
        return

    saved_cti_path = load_app_setting(SETTING_CTI_PATH)
    if saved_cti_path and os.path.exists(saved_cti_path):
        module_log.info(f"Attempting initialization with saved CTI: {saved_cti_path}")
        try:
            initialize_ic4_with_cti(
                saved_cti_path
            )  # This function will set IC4_INITIALIZED
            if IC4_INITIALIZED:
                module_log.info(
                    f"Successfully initialized IC4 with saved CTI: {saved_cti_path}"
                )
            else:
                # This case means initialize_ic4_with_cti was called but failed internally
                module_log.warning(
                    f"Failed to initialize with saved CTI: {saved_cti_path}. User will be prompted if app continues."
                )
        except (
            Exception
        ) as e:  # Catch exceptions from initialize_ic4_with_cti (e.g. FileNotFoundError or IC4 internal errors)
            module_log.error(
                f"Error during saved CTI initialization for {saved_cti_path}: {e}. User will be prompted."
            )
            IC4_INITIALIZED = False  # Ensure it's false
    else:
        if saved_cti_path:  # Path was saved but doesn't exist
            module_log.warning(
                f"Saved CTI path '{saved_cti_path}' not found. User will be prompted."
            )
        else:  # No CTI path saved at all
            module_log.info(
                "No saved CTI path found. User will be prompted by MainWindow."
            )
        IC4_INITIALIZED = False


def main_app_entry():
    log.info(
        f"Starting main_app_entry: IC4_AVAILABLE={IC4_AVAILABLE}, IC4_INITIALIZED={IC4_INITIALIZED}"
    )

    # Attempt to initialize IC4 with saved settings BEFORE creating QApplication and MainWindow
    attempt_saved_ic4_init()
    log.info(
        f"After attempt_saved_ic4_init: IC4_AVAILABLE={IC4_AVAILABLE}, IC4_INITIALIZED={IC4_INITIALIZED}"
    )

    # High-DPI support
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    # Application icon
    base_dir = os.path.dirname(os.path.abspath(__file__))
    ico = os.path.join(base_dir, "ui", "icons", "PRIM.ico")
    png = os.path.join(base_dir, "ui", "icons", "PRIM.png")
    icon = QIcon()
    if os.path.exists(ico):
        icon.addFile(ico)
    elif os.path.exists(png):
        icon.addFile(png)
    else:
        log.warning(f"Icon not found: {ico} or {png}")
    if not icon.isNull():
        app.setWindowIcon(icon)

    # Note: MainWindow will handle prompting for CTI if IC4_INITIALIZED is still False.
    # The generic warnings here are less critical now if MainWindow has specific handling.
    if not IC4_INITIALIZED:  # This check is after attempt_saved_ic4_init
        title = APP_NAME if "APP_NAME" in globals() else "Application"
        if (
            IC4_AVAILABLE
        ):  # IC4 module is there, but not initialized (e.g. saved CTI failed)
            log.warning(
                "IC Imaging Control SDK is available but not initialized (e.g. saved CTI failed or no CTI saved). "
                "MainWindow will attempt to guide the user."
            )
            # QMessageBox.warning( # This can be deferred to MainWindow logic
            #     None,
            #     f"{title} - Camera SDK Issue",
            #     "IC Imaging Control SDK available but not initialized. "
            #     "The application will guide you or use Setup Wizard to load a CTI.",
            # )
        elif not IC4_AVAILABLE and not os.environ.get(
            "PRIM_APP_TESTING_NO_IC4"
        ):  # Only show if not testing without IC4
            QMessageBox.critical(
                None,
                f"{title} - Camera SDK Missing",
                "imagingcontrol4 Python module not found. Camera functionality will be disabled. "
                "Please install it (e.g., 'pip install imagingcontrol4').",
            )

    # Global exception hook
    def custom_exception_handler(exc_type, value, tb):
        msg = "".join(traceback.format_exception(exc_type, value, tb))
        log.critical(f"UNCAUGHT EXCEPTION:\n{msg}")
        # Ensure APP_NAME is available
        app_title = APP_NAME if "APP_NAME" in globals() else "Application"
        dlg = QMessageBox(
            QMessageBox.Critical,
            f"{app_title} - Critical Error",
            "An unhandled error occurred. Please check the logs for more details.",
            QMessageBox.Ok,
        )
        dlg.setDetailedText(msg)
        dlg.exec_()

    sys.excepthook = custom_exception_handler

    # Load stylesheet
    style_path = os.path.join(base_dir, "style.qss")
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

    # Import and launch main window
    # Moved import here to ensure prim_app.IC4_INITIALIZED is set before MainWindow init
    from main_window import MainWindow

    main_win = MainWindow()
    version = CONFIG_APP_VERSION if "CONFIG_APP_VERSION" in globals() else "Unknown"
    main_win.setWindowTitle(f"{APP_NAME} v{version}")
    main_win.showMaximized()
    log.info("Main window shown.")

    # Connect cleanup
    # This check should reflect whether IC4 library was ever successfully used.
    if _ic4_init_has_run_successfully_this_session:
        app.aboutToQuit.connect(_cleanup_ic4)
        log.info("IC4 cleanup function connected to app.aboutToQuit.")
    else:
        log.info(
            "IC4 was not successfully initialized this session: skipping cleanup connect."
        )

    code = app.exec_()
    log.info(f"Exiting with code {code}.")
    sys.exit(code)


if __name__ == "__main__":
    launcher_log = logging.getLogger("prim_app_launcher")
    if not launcher_log.handlers:
        logging.basicConfig(
            level=logging.INFO,  # Or DEBUG for more verbose launch
            format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        )
    # This log is before any IC4 init attempt, so IC4_INITIALIZED will be its default False
    launcher_log.info(
        f"Launching prim_app.py. Initial IC4_INITIALIZED={IC4_INITIALIZED}"
    )
    main_app_entry()
