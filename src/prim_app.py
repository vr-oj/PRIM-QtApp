import sys
import os
import re
import traceback
import logging

# --- Attempt to import and initialize imagingcontrol4 at module level ---
# This ensures IC4_AVAILABLE and IC4_INITIALIZED are set when prim_app is imported.

# Define defaults first
IC4_AVAILABLE = False
IC4_INITIALIZED = False
ic4_library_module = None  # To hold the imported ic4 module

# Configure basic logging here so module-level logs are captured
# This will be overridden by the more specific config later if config.py is found
logging.basicConfig(
    level=logging.INFO,  # Default level
    format="%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] %(threadName)s - %(message)s",
)
module_log = logging.getLogger(__name__)  # Logger for this module's initial setup

try:
    import imagingcontrol4 as ic4

    ic4_library_module = ic4  # Store the module
    IC4_AVAILABLE = True
    module_log.info("imagingcontrol4 library found (module level check).")
    try:
        # Initialize library when this module (prim_app) is first loaded
        ic4.Library.init()
        IC4_INITIALIZED = True
        module_log.info(
            "imagingcontrol4 Library initialized successfully (module level)."
        )
    except ic4.IC4Exception as e:  # More specific exception
        module_log.error(
            f"Failed to initialize imagingcontrol4 library (module level): {e} (Code: {e.code})"
        )
        IC4_INITIALIZED = False
    except Exception as e:
        module_log.error(
            f"An unexpected error occurred during imagingcontrol4 library init (module level): {e}"
        )
        IC4_INITIALIZED = False
except ImportError:
    module_log.warning(
        "imagingcontrol4 library not found (module level check). Import failed."
    )
    IC4_AVAILABLE = False
    IC4_INITIALIZED = False
except Exception as e:  # Catch any other unexpected error during import itself
    module_log.error(f"Unexpected error importing imagingcontrol4 (module level): {e}")
    IC4_AVAILABLE = False
    IC4_INITIALIZED = False
# --- End of module-level IC4 initialization ---


from PyQt5.QtWidgets import QApplication, QMessageBox, QStyleFactory
from PyQt5.QtCore import Qt, QCoreApplication, QLoggingCategory

# Configuration & logging (this might reconfigure logging if APP_NAME and LOG_LEVEL are found)
try:
    from config import APP_NAME, LOG_LEVEL, APP_VERSION as CONFIG_APP_VERSION

    # Reconfigure logging based on config.py if needed
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    # Get root logger and remove existing handlers if any, then add new one
    # This is to avoid duplicate log messages if basicConfig was called before.
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] %(threadName)s - %(message)s",
    )
    log = logging.getLogger(__name__)  # Get logger after re-configuration
    log.info("Logging reconfigured from config.py.")
except ImportError:
    APP_NAME = "PRIM Application"  # Fallback
    CONFIG_APP_VERSION = "1.0"  # Fallback
    log = logging.getLogger(__name__)  # Get logger with default config
    log.warning(
        "config.py not found or APP_NAME/LOG_LEVEL missing. Using default logging."
    )
# Use module_log for consistency if log is not yet defined or reconfigured
module_log.info(f"Final IC4_INITIALIZED state: {IC4_INITIALIZED}")


logging.getLogger("matplotlib").setLevel(logging.WARNING)
QLoggingCategory.setFilterRules("qt.qss.styleSheet=false")
# log is now defined from the try-except block above


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


def _cleanup_ic4():  # Define cleanup function at module level
    if (
        IC4_INITIALIZED and ic4_library_module
    ):  # Check if it was initialized and module available
        try:
            ic4_library_module.Library.exit()
            log.info("imagingcontrol4 Library exited successfully.")
        except ic4_library_module.IC4Exception as e:
            log.error(f"Error exiting imagingcontrol4 library: {e} (Code: {e.code})")
        except Exception as e:
            log.error(
                f"An unexpected error occurred during imagingcontrol4 library exit: {e}"
            )


def main_app_entry():
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    # IC4 is already initialized (or attempted) at module import time.
    # We just need to check IC4_INITIALIZED.
    if not IC4_INITIALIZED and IC4_AVAILABLE:  # If available but failed to init
        QMessageBox.warning(
            None,
            "Camera SDK Error",
            f"TIS camera SDK (imagingcontrol4) was found but failed to initialize.\n"
            "TIS camera functionality will be unavailable. Check logs for details.",
        )
    elif not IC4_AVAILABLE:
        QMessageBox.warning(
            None,
            "Camera SDK Missing",
            f"TIS camera SDK (imagingcontrol4) not found.\n"
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
            log.warning("Processed QSS from %s was empty. Falling back.", style_path)
            app.setStyle(QStyleFactory.create("Fusion"))
    else:
        log.warning("style.qss not found at %s, using Fusion style.", style_path)
        app.setStyle(QStyleFactory.create("Fusion"))

    from main_window import MainWindow  # Import late

    window = MainWindow()
    window.setWindowTitle(f"{APP_NAME} v{CONFIG_APP_VERSION}")
    window.show()
    log.info("%s started.", APP_NAME)

    if IC4_INITIALIZED:  # Only connect cleanup if SDK was successfully initialized
        app.aboutToQuit.connect(_cleanup_ic4)

    sys.exit(app.exec_())


if __name__ == "__main__":
    # Any code here is run ONLY when this script is executed directly.
    # IC4 initialization is now done at module import time.
    log.info(f"Running prim_app.py as __main__. IC4_INITIALIZED is: {IC4_INITIALIZED}")
    main_app_entry()
