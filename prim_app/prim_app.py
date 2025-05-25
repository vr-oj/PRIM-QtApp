# PRIM-QTAPP/prim_app/prim_app.py
import sys
import os
import re
import traceback
import logging
from PyQt5.QtWidgets import QApplication, QMessageBox, QStyleFactory
from PyQt5.QtCore import Qt, QCoreApplication, QLoggingCategory
from PyQt5.QtGui import QIcon

# === IC4 Initialization Flags and Module Reference ===
IC4_AVAILABLE = False
IC4_INITIALIZED = False
ic4_library_module = None
_ic4_init_has_run_successfully_this_session = (
    False  # Tracks if init() has ever succeeded globally in this session
)

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
    Internal: initialize the IC Imaging Control library.
    This function attempts a global initialization. It can be called
    again after a specific CTI is loaded via initialize_ic4_with_cti.
    """
    global IC4_AVAILABLE, IC4_INITIALIZED, ic4_library_module, _ic4_init_has_run_successfully_this_session

    if _ic4_init_has_run_successfully_this_session and IC4_INITIALIZED:
        # If a previous init in this session was successful and we are still marked as initialized
        IC4_AVAILABLE = True  # Should be true if initialized
        if ic4_library_module is None and IC4_AVAILABLE:
            try:
                import imagingcontrol4 as ic4

                ic4_library_module = ic4
            except ImportError:  # Should not happen if IC4_AVAILABLE is true
                IC4_AVAILABLE = False
                IC4_INITIALIZED = False
        module_log.info(
            "IC4 library already successfully initialized in this session and flags are set."
        )
        return

    module_log.info("Attempting IC4 library global initialization...")
    try:
        if ic4_library_module is None:  # Ensure module is imported
            import imagingcontrol4 as ic4

            ic4_library_module = ic4
        IC4_AVAILABLE = True  # If import succeeded
        module_log.info("Imported imagingcontrol4 module for global init.")
        try:
            ic4_library_module.Library.init()
            IC4_INITIALIZED = True
            _ic4_init_has_run_successfully_this_session = (
                True  # Mark that init() succeeded at least once
            )
            module_log.info("ic4.Library.init() succeeded globally.")
            # Attempt to patch DeviceInfo.__del__ to suppress finalizer errors
            # This is a workaround; proper init/exit is preferred.
            try:
                import imagingcontrol4.devenum as _dev

                orig_del = getattr(
                    _dev.DeviceInfo, "__del__", None
                )  # Check if __del__ exists
                if orig_del:  # Only patch if it exists

                    def safe_del(self):
                        try:
                            orig_del(self)
                        except (
                            RuntimeError
                        ):  # Specifically for "Library.init was not called"
                            pass
                        except Exception:  # Catch any other __del__ exceptions silently
                            pass

                    _dev.DeviceInfo.__del__ = safe_del
                    module_log.debug("Patched DeviceInfo.__del__.")
            except Exception as patch_e:
                module_log.warning(f"Could not patch DeviceInfo destructor: {patch_e}")
        except Exception as init_e:
            msg = str(init_e).lower()
            if any(
                phrase in msg
                for phrase in (
                    "already called",
                    "already initialized",
                    "library is already initialized",
                )
            ):
                IC4_INITIALIZED = True  # Library reports it's already initialized
                _ic4_init_has_run_successfully_this_session = (
                    True  # Count this as a successful state
                )
                module_log.warning(
                    f"ic4.Library.init() reported already initialized: {init_e}"
                )
            else:
                IC4_INITIALIZED = False  # Failed to initialize
                # _ic4_init_has_run_successfully_this_session remains False or as previously set
                module_log.error(f"ic4.Library.init() failed globally: {init_e}")
    except ImportError:
        IC4_AVAILABLE = False
        IC4_INITIALIZED = False
        module_log.warning(
            "imagingcontrol4 library not found during global init attempt."
        )
    except Exception as imp_e:  # Catch other potential errors during import or setup
        IC4_AVAILABLE = False
        IC4_INITIALIZED = False
        module_log.error(
            f"Unexpected error during imagingcontrol4 import or global init: {imp_e}"
        )
    finally:
        module_log.info(
            f"Global IC4 flags after init attempt: AVAILABLE={IC4_AVAILABLE}, INITIALIZED={IC4_INITIALIZED}, SESSION_SUCCESS_FLAG={_ic4_init_has_run_successfully_this_session}"
        )


# === Perform early global initialization attempt ===
# This call attempts to initialize the IC4 library as soon as prim_app.py is loaded.
# It aligns with The Imaging Source's recommendation for early initialization.
_initialize_ic4_globally()


def initialize_ic4_with_cti(cti_path: str):
    """
    Load the specified GenTL producer (.cti) and (re)initialize the IC4 library.
    This should be called by the application when a CTI file is selected.
    """
    global _ic4_init_has_run_successfully_this_session, IC4_INITIALIZED, IC4_AVAILABLE, ic4_library_module
    module_log.info(f"Attempting to initialize IC4 with CTI: {cti_path}")

    # Optional: Cleanly exit any previous IC4 session.
    # This might be necessary if switching CTIs or to ensure a clean state.
    # However, ic4.Library.loadGenTLProducer is documented to unload previous producers.
    if IC4_INITIALIZED and ic4_library_module:
        try:
            # Consider if ic4_library_module.Library.exit() is truly needed here.
            # For now, we'll rely on loadGenTLProducer to handle transitions.
            # If issues arise, uncommenting exit() might be a step.
            # ic4_library_module.Library.exit()
            # module_log.info("Called Library.exit() before loading new CTI.")
            # IC4_INITIALIZED = False # Reflect that we've exited
            pass
        except Exception as e:
            module_log.warning(
                f"Exception during optional IC4 exit prior to CTI load: {e}"
            )

    try:
        # Ensure the imagingcontrol4 module is imported and available
        if ic4_library_module is None:
            import imagingcontrol4 as ic4

            ic4_library_module = ic4
        IC4_AVAILABLE = True  # If import is successful

        # Load the specified GenTL Producer
        ic4_library_module.Library.loadGenTLProducer(cti_path)
        module_log.info(f"Successfully called loadGenTLProducer with: {cti_path}")

        # Reset flags to force _initialize_ic4_globally to perform a fresh initialization
        # now that the new CTI is loaded.
        _ic4_init_has_run_successfully_this_session = False
        IC4_INITIALIZED = False  # Mark as not initialized before trying with new CTI

        _initialize_ic4_globally()  # Attempt to initialize with the new CTI loaded

        if not IC4_INITIALIZED:
            # This means _initialize_ic4_globally failed even after loading the CTI
            module_log.error(
                f"Failed to initialize IC4 library after loading CTI: {cti_path}. Check CTI validity and logs."
            )
            # Optionally, re-raise an error to inform the calling context (e.g., MainWindow)
            # raise RuntimeError(f"Failed to initialize IC4 with CTI {cti_path}")

    except Exception as e:
        module_log.error(
            f"Error during CTI loading ('{cti_path}') or subsequent initialization: {e}"
        )
        IC4_INITIALIZED = False  # Ensure this is false on any failure in this block
        IC4_AVAILABLE = False  # If CTI load fails, library is effectively not usable
        # Optionally re-raise to propagate the error
        # raise


# Configure logging from config.py if available
try:
    from utils.config import APP_NAME, LOG_LEVEL, APP_VERSION as CONFIG_APP_VERSION

    root_logger = logging.getLogger()  # Get root logger
    # Remove existing handlers to avoid duplicate logs if script is re-run in some envs
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
        h.close()

    log_level_from_config = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level_from_config,
        format="%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] %(threadName)s - %(message)s",
        force=True,  # Override any existing basicConfig
    )
    log = logging.getLogger(__name__)  # Logger for this module
    log.info(f"Logging reconfigured from config.py. Level set to {LOG_LEVEL.upper()}.")
except ImportError:
    APP_NAME = "PRIM Application"
    CONFIG_APP_VERSION = "1.0"  # Default version if config not found
    log = logging.getLogger(__name__)
    # Basic logging setup if config is not found
    if not log.handlers:  # Avoid adding handlers multiple times
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] %(threadName)s - %(message)s",
            force=True,
        )
    log.warning("Could not load utils.config; using default logging and app settings.")

# Suppress verbose matplotlib logs if matplotlib is used
logging.getLogger("matplotlib").setLevel(logging.WARNING)
# Suppress Qt QSS style sheet warnings if not desired
QLoggingCategory.setFilterRules("qt.qss.styleSheet=false")


def load_processed_qss(path):
    """Loads a QSS file and processes simple @variable: #color; definitions."""
    var_re = re.compile(r"@([A-Za-z0-9_]+):\s*(#[0-9A-Fa-f]{3,8});")
    vars_map = {}
    lines = []
    try:
        with open(path, "r") as f:
            for line_content in f:
                match = var_re.match(line_content)
                if match:
                    vars_map[match.group(1)] = match.group(2)
                else:
                    # Replace variables in the current line
                    processed_line = line_content
                    for var_name, var_value in vars_map.items():
                        processed_line = processed_line.replace(
                            f"@{var_name}", var_value
                        )
                    lines.append(processed_line)
        return "".join(lines)
    except FileNotFoundError:
        log.error(f"QSS file not found: {path}")
        return ""
    except Exception as e:
        log.error(f"Error processing QSS file {path}: {e}")
        return ""


def _cleanup_ic4():
    """Gracefully exit the IC4 library on application quit."""
    global IC4_INITIALIZED, ic4_library_module
    if IC4_INITIALIZED and ic4_library_module:
        try:
            log.info("Attempting to exit IC4 library...")
            ic4_library_module.Library.exit()
            log.info("IC4 library exited successfully.")
            IC4_INITIALIZED = False  # Update status
        except Exception as e:
            log.error(f"Error encountered during IC4 library exit: {e}")
    else:
        log.info(
            "IC4 library not initialized or module not available; skipping exit call."
        )


def main_app_entry():
    # Log initial IC4 status from the global scope
    log.info(
        f"Starting main_app_entry. IC4_AVAILABLE={IC4_AVAILABLE}, IC4_INITIALIZED={IC4_INITIALIZED}"
    )

    # High DPI settings
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    # Set application icon (ensure paths are correct)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    icon_path_ico = os.path.join(base_dir, "ui", "icons", "PRIM.ico")
    icon_path_png = os.path.join(base_dir, "ui", "icons", "PRIM.png")

    app_icon = QIcon()
    if os.path.exists(icon_path_ico):
        app_icon.addFile(icon_path_ico)
    elif os.path.exists(icon_path_png):
        app_icon.addFile(icon_path_png)
    else:
        log.warning(f"Application icon not found at {icon_path_ico} or {icon_path_png}")
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    # Warn if IC4 SDK is not properly initialized at this stage
    # This check happens after the early global init attempt.
    if not IC4_INITIALIZED:
        if IC4_AVAILABLE:  # Library was imported but init() failed or CTI needed
            QMessageBox.warning(
                None,  # Parent
                f"{APP_NAME} - Camera SDK Issue",
                "The ImagingControl4 SDK was found but could not be fully initialized. "
                "Please ensure a GenTL producer (CTI file) is correctly installed and accessible, "
                "or select one via the Camera Setup wizard. Some camera features may be unavailable.",
            )
        else:  # Library could not be imported
            QMessageBox.critical(
                None,  # Parent
                f"{APP_NAME} - Camera SDK Missing",
                "The ImagingControl4 SDK (imagingcontrol4 python module) could not be found. "
                "Camera functionalities will be disabled. Please install the SDK.",
            )

    # Global exception handler
    def custom_exception_handler(exception_type, value, tb):
        error_message = "".join(traceback.format_exception(exception_type, value, tb))
        log.critical(f"UNCAUGHT EXCEPTION:\n{error_message}")

        # Basic fallback dialog if APP_NAME is not defined
        app_title = APP_NAME if "APP_NAME" in globals() and APP_NAME else "Application"

        msg_box = QMessageBox(
            QMessageBox.Critical,  # Icon
            f"{app_title} - Critical Error",  # Title
            "An unhandled error occurred, and the application may need to close. Please check the logs.",  # Text
            QMessageBox.Ok,  # Buttons
        )
        msg_box.setDetailedText(error_message)  # Allow user to see details
        msg_box.exec_()
        # Depending on the severity or type of error, you might want to exit:
        # sys.exit(1)

    sys.excepthook = custom_exception_handler

    # Load QSS style
    style_sheet_path = os.path.join(
        base_dir, "style.qss"
    )  # Assuming style.qss is in the same dir as prim_app.py
    if os.path.exists(style_sheet_path):
        qss_content = load_processed_qss(style_sheet_path)
        if qss_content:
            app.setStyleSheet(qss_content)
            log.info(f"Applied QSS stylesheet from {style_sheet_path}")
        else:
            log.warning(
                f"Failed to load or process QSS from {style_sheet_path}. Using default style."
            )
            app.setStyle(QStyleFactory.create("Fusion"))  # Fallback style
    else:
        log.info(
            f"Stylesheet {style_sheet_path} not found. Using default style 'Fusion'."
        )
        app.setStyle(QStyleFactory.create("Fusion"))

    # Import MainWindow after global setups (like logging, excepthook)
    from main_window import MainWindow  # Ensure this import is after sys.excepthook

    main_win = MainWindow()  # Create the main window instance

    # Use CONFIG_APP_VERSION if available from config, else a default
    app_version_str = (
        CONFIG_APP_VERSION
        if "CONFIG_APP_VERSION" in globals() and CONFIG_APP_VERSION
        else "Unknown"
    )
    main_win.setWindowTitle(f"{APP_NAME} v{app_version_str}")
    main_win.showMaximized()
    log.info(f"{APP_NAME} main window displayed.")

    # Connect cleanup function for IC4 library on application exit
    # Only connect if IC4 was initialized to avoid errors during cleanup
    if IC4_INITIALIZED:
        app.aboutToQuit.connect(_cleanup_ic4)
    else:
        log.info(
            "IC4 not initialized, skipping connection of _cleanup_ic4 to aboutToQuit."
        )

    exit_code = app.exec_()
    log.info(f"Application exiting with code {exit_code}.")
    sys.exit(exit_code)


if __name__ == "__main__":
    # The main logger for the application entry point.
    # The 'log' variable will be configured by basicConfig within main_app_entry based on utils.config
    # For this initial log message, use the module_log or get a new logger instance.
    initial_log = logging.getLogger("prim_app_launcher")
    if (
        not initial_log.handlers
    ):  # Ensure basic config if called directly and config fails
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        )

    initial_log.info(
        f"Launching {os.path.basename(__file__)}. Initial IC4_INITIALIZED state (before global init): {IC4_INITIALIZED}"
    )
    main_app_entry()
