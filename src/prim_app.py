import sys
import os
import re
import traceback
import logging

# --- Module-level IC4 Initialization Block ---
# Define defaults first
IC4_AVAILABLE = False
IC4_INITIALIZED = False  # This will be the single source of truth
ic4_library_module = None  # To hold the imported 'ic4' module
_ic4_init_attempt_complete = (
    False  # Flag to ensure the init logic runs only once effectively
)

# Configure basic logging here for module-level activities BEFORE config.py might reconfigure it.
# This ensures these early logs are captured.
module_log = logging.getLogger("prim_app_module_setup")  # Specific logger name
# Avoid adding handlers if root logger already has them from a previous import or if this runs multiple times
if not module_log.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] - %(message)s"
    )
    handler.setFormatter(formatter)
    module_log.addHandler(handler)
    module_log.setLevel(logging.INFO)  # Default to INFO for these setup logs


def _initialize_ic4_globally():
    """
    Tries to initialize the IC4 library. Should only effectively run init() once.
    Sets global IC4_AVAILABLE, IC4_INITIALIZED, and ic4_library_module.
    """
    global IC4_AVAILABLE, IC4_INITIALIZED, ic4_library_module, _ic4_init_attempt_complete

    if (
        _ic4_init_attempt_complete and IC4_INITIALIZED
    ):  # If successfully initialized once, do nothing more.
        module_log.info(
            "IC4 library already successfully initialized. Skipping re-init attempt."
        )
        return

    if (
        _ic4_init_attempt_complete and not IC4_INITIALIZED
    ):  # If attempted and failed, don't retry.
        module_log.info(
            "IC4 library initialization previously attempted and failed. Skipping re-init attempt."
        )
        return

    module_log.info("Attempting IC4 library initialization sequence...")
    _ic4_init_attempt_complete = True  # Mark that we are attempting/have attempted.

    try:
        import imagingcontrol4 as ic4

        ic4_library_module = ic4  # Store the imported module reference
        IC4_AVAILABLE = True
        module_log.info("imagingcontrol4 library module imported.")
        try:
            ic4.Library.init()
            IC4_INITIALIZED = True  # Set to True on successful init
            module_log.info("ic4.Library.init() called successfully.")
        except ic4.IC4Exception as e:
            # Check if the specific error is that it's already initialized
            # The error message from the log is: "Library.init was already called"
            err_msg_lower = str(e).lower()
            if (
                "already called" in err_msg_lower
                or "already been initialized" in err_msg_lower
            ):
                module_log.warning(
                    f"ic4.Library.init() indicated already initialized: {e}. Considering this a success."
                )
                IC4_INITIALIZED = (
                    True  # If already initialized by a previous load, treat as success
                )
            else:
                module_log.error(
                    f"Failed to initialize imagingcontrol4 library: {e} (Code: {e.code if hasattr(e,'code') else 'N/A'})"
                )
                IC4_INITIALIZED = False  # Explicitly False on other errors
        except Exception as e:  # Other errors during init()
            module_log.error(f"Unexpected error during ic4.Library.init(): {e}")
            IC4_INITIALIZED = False
    except ImportError:
        module_log.warning("imagingcontrol4 library (ic4) not found on import.")
        IC4_AVAILABLE = False
        IC4_INITIALIZED = False
    except Exception as e:  # Other errors during import imagingcontrol4
        module_log.error(f"Unexpected error importing imagingcontrol4: {e}")
        IC4_AVAILABLE = False
        IC4_INITIALIZED = False

    module_log.info(
        f"IC4 initialization sequence complete. AVAILABLE: {IC4_AVAILABLE}, INITIALIZED: {IC4_INITIALIZED}"
    )


# Call the initialization function when this module (prim_app.py) is first loaded.
_initialize_ic4_globally()
# --- End of module-level IC4 initialization ---


from PyQt5.QtWidgets import QApplication, QMessageBox, QStyleFactory
from PyQt5.QtCore import Qt, QCoreApplication, QLoggingCategory

# Configuration & logging (this might reconfigure logging if config.py is found)
# The main application logger 'log' will be set up here.
try:
    from config import APP_NAME, LOG_LEVEL, APP_VERSION as CONFIG_APP_VERSION

    # Reconfigure ROOT logging based on config.py
    # This ensures all subsequent loggers inherit this configuration.
    # Remove existing handlers from root to avoid duplicate messages if this is re-run in some context
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close()  # Explicitly close handler

    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] %(threadName)s - %(message)s",
        force=True,  # force=True (Python 3.8+) reconfigures root logger
    )
    log = logging.getLogger(
        __name__
    )  # Get logger for the current module (__main__ or prim_app)
    log.info("Root logging reconfigured from config.py.")
except ImportError:
    APP_NAME = "PRIM Application"
    CONFIG_APP_VERSION = "1.0"
    log = logging.getLogger(__name__)
    log.warning(
        "config.py not found or APP_NAME/LOG_LEVEL missing. Using existing logging config for this module."
    )
except Exception as e:
    log = logging.getLogger(__name__)
    log.error(f"Error loading config.py or reconfiguring logging: {e}")


log.info(f"After config, prim_app module's IC4_INITIALIZED state: {IC4_INITIALIZED}")


logging.getLogger("matplotlib").setLevel(logging.WARNING)
QLoggingCategory.setFilterRules("qt.qss.styleSheet=false")


def load_processed_qss(path):
    var_def = re.compile(r"@([A-Za-z0-9_]+):\s*(#[0-9A-Fa-f]{3,8});")
    vars_map = {}
    lines = []
    try:
        with open(path, "r") as f:
            for line in f:
                m = var_def.match(line)
                if m:
                    vars_map[m.group(1)] = m.group(2)
                else:
                    for name, hexval in vars_map.items():
                        line = line.replace(f"@{name}", hexval)
                    lines.append(line)
        return "".join(lines)
    except Exception as e:
        log.error(f"Failed to load or process QSS file {path}: {e}")
        return ""


def _cleanup_ic4():
    if IC4_INITIALIZED and ic4_library_module:
        try:
            log.info("Attempting to exit imagingcontrol4 Library...")
            ic4_library_module.Library.exit()
            log.info("imagingcontrol4 Library exited successfully.")
        except ic4_library_module.IC4Exception as e:
            log.error(
                f"Error exiting imagingcontrol4 library: {e} (Code: {e.code if hasattr(e,'code') else 'N/A'})"
            )
        except Exception as e:
            log.error(
                f"An unexpected error occurred during imagingcontrol4 library exit: {e}"
            )
    else:
        log.info(
            "Skipping imagingcontrol4 Library exit (not initialized or module not available)."
        )


def main_app_entry():
    # Ensure _initialize_ic4_globally() has run. It runs on module import.
    # Log the state again here for clarity when main_app_entry starts.
    log.info(
        f"main_app_entry started. IC4_AVAILABLE: {IC4_AVAILABLE}, IC4_INITIALIZED: {IC4_INITIALIZED}"
    )

    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    if (
        not IC4_INITIALIZED
    ):  # Show warning if not successfully initialized for any reason
        if IC4_AVAILABLE:  # Found but failed to init
            QMessageBox.warning(
                None,
                "Camera SDK Problem",
                f"TIS camera SDK (imagingcontrol4) was found but could not be initialized.\n"
                "TIS camera functionality will be unavailable. Please check logs for details.",
            )
        else:  # Not found at all
            QMessageBox.warning(
                None,
                "Camera SDK Missing",
                f"TIS camera SDK (imagingcontrol4) was not found.\n"
                "TIS camera functionality will be unavailable.",
            )

    def _handle_exception(exc_type, exc_value, exc_tb):
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log.critical("UNCAUGHT EXCEPTION:\n%s", msg)
        parent_widget = app.activeWindow()
        dlg = QMessageBox(
            QMessageBox.Critical,
            f"{APP_NAME} - Error",
            "An unexpected error occurred. Please check the logs.",
            QMessageBox.Ok,
            parent_widget,
        )
        dlg.setDetailedText(msg)
        dlg.exec_()

    sys.excepthook = _handle_exception

    style_path = os.path.join(os.path.dirname(__file__), "style.qss")
    if os.path.exists(style_path):
        qss = load_processed_qss(style_path)
        if qss:
            app.setStyleSheet(qss)
            log.info("Loaded and applied processed QSS from %s", style_path)
        else:
            log.warning(
                "Processed QSS from %s was empty or failed to load. Falling back.",
                style_path,
            )
            app.setStyle(QStyleFactory.create("Fusion"))
    else:
        log.warning("style.qss not found at %s, using Fusion style.", style_path)
        app.setStyle(QStyleFactory.create("Fusion"))

    from main_window import MainWindow

    window = MainWindow()
    window.setWindowTitle(f"{APP_NAME} v{CONFIG_APP_VERSION}")
    window.show()
    log.info("%s started.", APP_NAME)

    if IC4_INITIALIZED:
        app.aboutToQuit.connect(_cleanup_ic4)
    else:
        log.info("IC4 SDK not initialized, cleanup on quit will be skipped.")

    sys.exit(app.exec_())


if __name__ == "__main__":
    # The _initialize_ic4_globally() function runs when this module is first imported or run.
    # So, IC4_INITIALIZED reflects the state of that single attempt.
    log.info(f"Running prim_app.py as __main__. IC4_INITIALIZED is: {IC4_INITIALIZED}")
    main_app_entry()
