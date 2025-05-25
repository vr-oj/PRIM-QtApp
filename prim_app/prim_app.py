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
    try:
        if ic4_library_module is None:
            import imagingcontrol4 as ic4

            ic4_library_module = ic4
        # Load the CTI
        ic4_library_module.Library.loadGenTLProducer(cti_path)
        IC4_AVAILABLE = True
        module_log.info(f"Loaded CTI: {cti_path}")
        # Initialize the library
        ic4_library_module.Library.init()
        IC4_INITIALIZED = True
        _ic4_init_has_run_successfully_this_session = True
        module_log.info("IC4 Library.init() succeeded after CTI load.")
    except Exception as e:
        IC4_AVAILABLE = False
        IC4_INITIALIZED = False
        module_log.error(f"Failed to initialize IC4 with CTI {cti_path}: {e}")


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
        log.info("IC4 not initialized: skipping cleanup.")


def main_app_entry():
    log.info(
        f"Starting main_app_entry: AVAILABLE={IC4_AVAILABLE}, INITIALIZED={IC4_INITIALIZED}"
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

    # Warn if IC4 not initialized
    if not IC4_INITIALIZED:
        title = APP_NAME
        if IC4_AVAILABLE:
            QMessageBox.warning(
                None,
                f"{title} - Camera SDK Issue",
                "IC Imaging Control SDK imported but not initialized. "
                "Load a CTI via the Setup Wizard to enable camera features.",
            )
        else:
            QMessageBox.critical(
                None,
                f"{title} - SDK Missing",
                "imagingcontrol4 module not found. Camera disabled.",
            )

    # Global exception hook
    def custom_exception_handler(exc_type, value, tb):
        msg = "".join(traceback.format_exception(exc_type, value, tb))
        log.critical(f"UNCAUGHT EXCEPTION:\n{msg}")
        dlg = QMessageBox(
            QMessageBox.Critical,
            f"{APP_NAME} - Critical Error",
            "An unhandled error occurred. Check logs.",
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
    from main_window import MainWindow

    main_win = MainWindow()
    version = CONFIG_APP_VERSION if "CONFIG_APP_VERSION" in globals() else "Unknown"
    main_win.setWindowTitle(f"{APP_NAME} v{version}")
    main_win.showMaximized()
    log.info("Main window shown.")

    # Connect cleanup
    if IC4_INITIALIZED:
        app.aboutToQuit.connect(_cleanup_ic4)
    else:
        log.info("IC4 not initialized: skipping cleanup connect.")

    code = app.exec_()
    log.info(f"Exiting with code {code}.")
    sys.exit(code)


if __name__ == "__main__":
    launcher_log = logging.getLogger("prim_app_launcher")
    if not launcher_log.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        )
    launcher_log.info(f"Launching prim_app.py. IC4_INITIALIZED={IC4_INITIALIZED}")
    main_app_entry()
