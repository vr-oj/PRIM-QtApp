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

# === IC4 library import & availability flag ===
try:
    import imagingcontrol4 as ic4

    IC4_AVAILABLE = True
    ic4_library_module = ic4  # Store the module itself for Library.exit()
    module_log.info("imagingcontrol4 module imported successfully")
except ImportError:
    IC4_AVAILABLE = False
    ic4_library_module = None  # Ensure it's defined for cleanup check
    module_log.error(
        "Could not import imagingcontrol4 — camera functionality will be disabled."
    )

# === IC4 Initialization Flags ===
IC4_LIBRARY_INITIALIZED = False
IC4_GENTL_SYSTEM_CONFIGURED = (
    False  # Tracks if CTI path is set and GenTL path is updated
)


def initialize_ic4_with_cti(cti_path: str):
    """
    Persist CTI path, update GENICAM_GENTL64_PATH, and initialize IC4 idempotently.
    """
    global IC4_LIBRARY_INITIALIZED, IC4_GENTL_SYSTEM_CONFIGURED, IC4_AVAILABLE, ic4_library_module

    if not ic4_library_module:  # If IC4 wasn't imported, can't proceed
        module_log.error("Cannot initialize IC4: imagingcontrol4 module not available.")
        IC4_AVAILABLE = False
        return

    # 1) Persist choice
    try:
        save_app_setting(SETTING_CTI_PATH, cti_path)
    except Exception as e:
        module_log.warning(f"Failed to save CTI path setting: {e}")

    # 2) Add CTI folder to GenTL path
    cti_dir = os.path.dirname(cti_path)
    env_key = "GENICAM_GENTL64_PATH"
    existing = os.environ.get(env_key, "")
    paths = (
        existing.split(os.pathsep) if existing and existing.strip() else []
    )  # Handle empty existing path
    if cti_dir not in paths:
        new_paths_list = [cti_dir] + [
            p for p in paths if p
        ]  # Filter out empty paths from existing
        new_paths_env_str = os.pathsep.join(new_paths_list)
        os.environ[env_key] = new_paths_env_str
        module_log.info(f"Set {env_key}={new_paths_env_str}")
    else:
        module_log.info(f"CTI directory '{cti_dir}' already in {env_key}.")

    # 3) Initialize the IC4 library only once
    try:
        if not IC4_LIBRARY_INITIALIZED:
            ic4_library_module.Library.init()  # Use stored module
            module_log.info("ic4.Library.init() succeeded")
            IC4_LIBRARY_INITIALIZED = True  # Set flag on successful init
        else:
            module_log.debug("ic4.Library.init() already called; skipping")
    except RuntimeError as e:  # Catch specific RuntimeError for "already called"
        msg = str(e).lower()
        if "already called" in msg or "already initialized" in msg:  # More robust check
            module_log.debug(
                "Treating repeated ic4.Library.init() call as success (already initialized)."
            )
            IC4_LIBRARY_INITIALIZED = True  # Ensure flag is true if it was already init
        else:
            module_log.error(f"Unexpected RuntimeError during ic4.Library.init(): {e}")
            # Potentially set IC4_AVAILABLE to False or re-raise if critical
            raise  # Re-raise other RuntimeErrors
    except ic4.IC4Exception as e_ic4:  # Catch IC4 specific exceptions
        module_log.error(
            f"IC4Exception during ic4.Library.init(): {e_ic4} (Code: {e_ic4.code})"
        )
        # This could be critical, might prevent camera use
        raise  # Re-raise to indicate failure
    except Exception as e_gen:  # Catch other general exceptions
        module_log.error(f"Generic exception during ic4.Library.init(): {e_gen}")
        raise

    # 4) Update flags
    if IC4_LIBRARY_INITIALIZED:
        IC4_GENTL_SYSTEM_CONFIGURED = True
        IC4_AVAILABLE = True  # If init succeeded, IC4 is definitely available for use
    else:  # If init failed for some reason not caught as "already initialized"
        IC4_GENTL_SYSTEM_CONFIGURED = False
        IC4_AVAILABLE = False


def is_ic4_fully_initialized():
    """Checks if IC4 init and CTI configured."""
    return IC4_LIBRARY_INITIALIZED and IC4_GENTL_SYSTEM_CONFIGURED and IC4_AVAILABLE


# === Configure logging from utils.config ===
try:
    from utils.config import (
        APP_NAME as CONFIG_APP_NAME,
        LOG_LEVEL,
        APP_VERSION as CONFIG_APP_VERSION,
    )

    APP_NAME = CONFIG_APP_NAME
    log_level_from_config = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level_from_config,
        format="%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] %(threadName)s - %(message)s",
        force=True,  # Override any existing basicConfig
    )
    log = logging.getLogger(__name__)  # Get logger for this file
    log.info(f"Logging configured: Level set to {LOG_LEVEL.upper()}")
except ImportError:
    APP_NAME = "PRIM Application (Default)"
    CONFIG_APP_VERSION = "1.0d"  # Default version if config is missing
    log = logging.getLogger(__name__)
    if not log.handlers:  # Ensure basicConfig is called if not done by try block
        logging.basicConfig(
            level=logging.INFO,  # Default log level
            format="%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] %(threadName)s - %(message)s",
        )
    log.warning(
        "utils.config missing or incomplete: using default APP_NAME, VERSION, and INFO log level."
    )

# Suppress noisy logs from other libraries
logging.getLogger("matplotlib").setLevel(logging.WARNING)
QLoggingCategory.setFilterRules(
    "qt.qss.styleSheet=false"
)  # Suppress Qt QSS warnings if any


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


def _cleanup_ic4():
    global IC4_LIBRARY_INITIALIZED, IC4_GENTL_SYSTEM_CONFIGURED
    if IC4_LIBRARY_INITIALIZED and ic4_library_module:  # Check if module itself exists
        try:
            log.info("Exiting IC4 library via ic4.Library.exit()...")
            ic4_library_module.Library.exit()
            IC4_LIBRARY_INITIALIZED = False
            # IC4_GENTL_SYSTEM_CONFIGURED might remain true if path was set,
            # but library being exited means it's not actively configured for use.
            # For simplicity, we can reset it, or leave it as an indicator that setup was attempted.
            # Let's reset it to reflect the library is no longer active.
            IC4_GENTL_SYSTEM_CONFIGURED = False
            log.info("IC4 library exited successfully.")
        except Exception as e:
            log.warning(f"Error during ic4.Library.exit(): {e}")
    else:
        log.info(
            "IC4 library not initialized or module not available: skipping cleanup."
        )


def attempt_saved_ic4_init():
    """Attempts to initialize IC4 using a CTI path saved in app settings."""
    if not APP_SETTINGS_AVAILABLE:
        module_log.warning(
            "Application settings unavailable: cannot auto-initialize CTI path."
        )
        return

    saved_cti_path = load_app_setting(SETTING_CTI_PATH)
    if saved_cti_path and os.path.exists(saved_cti_path):
        module_log.info(
            f"Attempting to auto-initialize with saved CTI path: {saved_cti_path}"
        )
        try:
            initialize_ic4_with_cti(
                saved_cti_path
            )  # This function now updates global flags
            if is_ic4_fully_initialized():
                module_log.info(
                    "IC4 fully initialized successfully from saved CTI path."
                )
            else:
                module_log.warning(
                    "IC4 auto-initialization with saved CTI path did not result in a fully initialized state."
                )
        except Exception as e:
            module_log.error(
                f"Error during auto-initialization with saved CTI path '{saved_cti_path}': {e}"
            )
            # Ensure flags reflect failure if an exception occurs that isn't handled within initialize_ic4_with_cti
            global IC4_LIBRARY_INITIALIZED, IC4_GENTL_SYSTEM_CONFIGURED, IC4_AVAILABLE
            IC4_LIBRARY_INITIALIZED = False
            IC4_GENTL_SYSTEM_CONFIGURED = False
            IC4_AVAILABLE = (
                False if ic4_library_module is None else True
            )  # Keep IC4_AVAILABLE true if module loaded but init failed

    else:
        if saved_cti_path:  # Path was saved but doesn't exist
            module_log.warning(
                f"Saved CTI path '{saved_cti_path}' not found. User will be prompted if needed."
            )
        else:  # No CTI path saved
            module_log.info(
                "No saved CTI path found. User will be prompted if camera features are accessed."
            )


def main_app_entry():
    # Initial log before any major operations
    log.info(
        f"Application starting... Name: {APP_NAME}, Version: {CONFIG_APP_VERSION if 'CONFIG_APP_VERSION' in globals() else 'N/A'}"
    )
    log.debug(
        f"Initial IC4 status: AVAILABLE={IC4_AVAILABLE}, LIB_INITED={IC4_LIBRARY_INITIALIZED}, CTI_CONFIGURED={IC4_GENTL_SYSTEM_CONFIGURED}"
    )

    attempt_saved_ic4_init()  # Try to init with saved CTI first

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

    # Check IC4 availability and show message if critical features are disabled
    if not IC4_AVAILABLE and not os.environ.get(
        "PRIM_APP_TESTING_NO_IC4"
    ):  # Allow testing override
        QMessageBox.critical(
            None,  # Parent
            f"{APP_NAME} - Camera SDK Missing",
            "The 'imagingcontrol4' Python module was not found or failed to load.\nCamera-related features will be disabled.",
        )
    elif (
        not is_ic4_fully_initialized() and IC4_AVAILABLE
    ):  # IC4 module is there, but not fully set up (e.g. CTI missing/failed)
        log.warning(
            "IC4 module is available but not fully initialized (e.g. CTI issue). Camera features might be limited."
        )
        # A non-critical warning might be shown in MainWindow status bar later.

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

    # Connect IC4 cleanup to application's aboutToQuit signal
    if IC4_LIBRARY_INITIALIZED:  # Only connect if it was actually initialized
        app.aboutToQuit.connect(_cleanup_ic4)
    else:
        log.info(
            "IC4 library was not initialized, skipping connection of _cleanup_ic4 to aboutToQuit."
        )

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
    launcher_log.info(
        f"Launching prim_app.py script... Initial IC4_LIB_INITED={IC4_LIBRARY_INITIALIZED}, CTI_CFG={IC4_GENTL_SYSTEM_CONFIGURED}"
    )
    main_app_entry()
