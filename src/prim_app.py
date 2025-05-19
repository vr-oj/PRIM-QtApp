import sys
import os
import re
import traceback
import logging

from PyQt5.QtWidgets import QApplication, QMessageBox, QStyleFactory
from PyQt5.QtCore import Qt, QCoreApplication, QLoggingCategory

# ─── Configuration & logging ────────────────────────────────────────────────
try:
    from config import APP_NAME, LOG_LEVEL

    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] %(threadName)s - %(message)s",
    )
except ImportError:
    APP_NAME = "PRIM Application"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

# ─── Reduce matplotlib logging noise ───────────────────────────────────────
logging.getLogger("matplotlib").setLevel(logging.WARNING)
# ─── Suppress Qt QSS parsing warnings ──────────────────────────────────────
QLoggingCategory.setFilterRules("qt.qss.styleSheet=false")

log = logging.getLogger(__name__)

# ─── Optional TIS camera library ────────────────────────────────────────────
IC4_AVAILABLE = False
IC4_INITIALIZED = False
try:
    import imagingcontrol4 as ic4

    IC4_AVAILABLE = True
    log.info("imagingcontrol4 library found.")
except ImportError:
    IC4_AVAILABLE = False
    log.warning(
        "imagingcontrol4 library not found; TIS camera functions will be disabled."
    )
except Exception as e:
    IC4_AVAILABLE = False
    log.error(f"Error importing imagingcontrol4: {e}")


# ─── QSS preprocessing to handle variables ─────────────────────────────────
def load_processed_qss(path):
    var_def = re.compile(
        r"@([A-Za-z0-9_]+):\s*(#[0-9A-Fa-f]{3,8});"
    )  # Allow 3,4,6,8 hex digit colors
    vars_map = {}  # Renamed to avoid conflict
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


# ─── Application entry point ─────────────────────────────────────────────────
def main_app_entry():
    global IC4_INITIALIZED  # To track if init was successful

    # enable High DPI scaling
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    # initialize ic4 if available
    if IC4_AVAILABLE:
        try:
            ic4.Library.init()
            IC4_INITIALIZED = True
            log.info("imagingcontrol4 Library initialized successfully.")
        except IC4Exception as e:  # More specific exception
            log.error(
                f"Failed to initialize imagingcontrol4 library: {e} (Code: {e.code})"
            )
            IC4_INITIALIZED = False  # Explicitly mark as not initialized
            QMessageBox.warning(
                None,
                "Camera SDK Error",
                f"Failed to initialize TIS camera SDK: {e}\n"
                "TIS camera functionality will be unavailable.",
            )
        except Exception as e:
            log.error(
                f"An unexpected error occurred during imagingcontrol4 library initialization: {e}"
            )
            IC4_INITIALIZED = False
            QMessageBox.warning(
                None,
                "Camera SDK Error",
                f"Unexpected error initializing TIS camera SDK: {e}\n"
                "TIS camera functionality will be unavailable.",
            )

    # global exception handler
    def _handle_exception(exc_type, exc_value, exc_tb):
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log.critical("UNCAUGHT EXCEPTION:\n%s", msg)
        # Ensure MainWindow or a generic parent is used if window is not available
        parent_widget = app.activeWindow()  # Try to get current active window
        dlg = QMessageBox(
            QMessageBox.Critical,
            f"{APP_NAME} - Error",
            "An unexpected error occurred. Please check the logs.",
            QMessageBox.Ok,
            parent_widget,
        )
        dlg.setDetailedText(msg)
        dlg.exec_()
        # Decide if app should exit on unhandled exception
        # sys.exit(1)

    sys.excepthook = _handle_exception

    # load stylesheet or fall back to Fusion
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

    # import MainWindow late to avoid circular dependencies and after SDK init attempt
    from main_window import MainWindow

    window = MainWindow()
    window.setWindowTitle(
        f"{APP_NAME} v{APP_VERSION if 'APP_VERSION' in globals() else 'N/A'}"
    )
    window.show()
    log.info("%s started.", APP_NAME)

    # clean up ic4 on quit
    if IC4_INITIALIZED:  # Only exit if successfully initialized

        def _cleanup_ic4():
            try:
                ic4.Library.exit()
                log.info("imagingcontrol4 Library exited successfully.")
            except IC4Exception as e:  # More specific exception
                log.error(
                    f"Error exiting imagingcontrol4 library: {e} (Code: {e.code})"
                )
            except Exception as e:
                log.error(
                    f"An unexpected error occurred during imagingcontrol4 library exit: {e}"
                )

        app.aboutToQuit.connect(_cleanup_ic4)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main_app_entry()
