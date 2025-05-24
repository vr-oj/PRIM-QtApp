import sys
import os
import re
import traceback
import logging

# === IC4 Initialization Flags and Module Reference ===
IC4_AVAILABLE = False
IC4_INITIALIZED = False
ic4_library_module = None
_ic4_init_has_run_successfully_this_session = (
    False  # Tracks if init() has ever succeeded
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
    Internal: initialize the IC Imaging Control library once the correct GenTL producer is loaded.
    """
    global IC4_AVAILABLE, IC4_INITIALIZED, ic4_library_module, _ic4_init_has_run_successfully_this_session

    if _ic4_init_has_run_successfully_this_session:
        IC4_AVAILABLE = True
        IC4_INITIALIZED = True
        if ic4_library_module is None:
            try:
                import imagingcontrol4 as ic4

                ic4_library_module = ic4
            except ImportError:
                IC4_AVAILABLE = False
                IC4_INITIALIZED = False
        module_log.info("IC4 library already initialized this session.")
        return

    module_log.info("Attempting IC4 library initialization...")
    try:
        import imagingcontrol4 as ic4

        ic4_library_module = ic4
        IC4_AVAILABLE = True
        module_log.info("Imported imagingcontrol4 module.")
        try:
            ic4.Library.init()
            IC4_INITIALIZED = True
            _ic4_init_has_run_successfully_this_session = True
            module_log.info("ic4.Library.init() succeeded.")
            # Patch DeviceInfo.__del__ to suppress finalizer errors
            try:
                import imagingcontrol4.devenum as _dev

                orig_del = _dev.DeviceInfo.__del__

                def safe_del(self):
                    try:
                        orig_del(self)
                    except RuntimeError:
                        pass

                _dev.DeviceInfo.__del__ = safe_del
                module_log.info("Patched DeviceInfo.__del__ successfully.")
            except Exception as e:
                module_log.warning(f"Could not patch DeviceInfo destructor: {e}")
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
                IC4_INITIALIZED = True
                _ic4_init_has_run_successfully_this_session = True
                module_log.warning(f"init() reported already initialized: {init_e}")
            else:
                IC4_INITIALIZED = False
                module_log.error(f"ic4.Library.init() failed: {init_e}")
    except ImportError:
        IC4_AVAILABLE = False
        IC4_INITIALIZED = False
        module_log.warning("imagingcontrol4 not found.")
    except Exception as imp_e:
        IC4_AVAILABLE = False
        IC4_INITIALIZED = False
        module_log.error(f"Unexpected import error: {imp_e}")
    finally:
        module_log.info(
            f"IC4_AVAILABLE={IC4_AVAILABLE}, IC4_INITIALIZED={IC4_INITIALIZED}"
        )


def initialize_ic4_with_cti(cti_path: str):
    """
    Load the specified GenTL producer (.cti) and reinitialize the IC4 library.
    Must be called before any device enumeration or grabbing.
    """
    # Attempt to clean up any existing initialization
    try:
        if ic4_library_module and IC4_INITIALIZED:
            ic4_library_module.Library.exit()
            module_log.info("Exited previous IC4 session.")
    except Exception:
        module_log.warning("Failed to exit IC4 cleanly, proceeding anyway.")

    # Load the new CTI and init
    try:
        import imagingcontrol4 as ic4

        ic4.Library.loadGenTLProducer(cti_path)
        module_log.info(f"Loaded GenTL producer: {cti_path}")
    except Exception as e:
        module_log.error(f"Failed to load CTI '{cti_path}': {e}")
        raise
    # Reset session flag so init() can run
    global _ic4_init_has_run_successfully_this_session
    _ic4_init_has_run_successfully_this_session = False
    _initialize_ic4_globally()


# Note: No module-level IC4 initialization call here; defer until after CTI load


from PyQt5.QtWidgets import QApplication, QMessageBox, QStyleFactory
from PyQt5.QtCore import Qt, QCoreApplication, QLoggingCategory
from PyQt5.QtGui import QIcon

# Configure logging from config.py if available
try:
    from utils.config import APP_NAME, LOG_LEVEL, APP_VERSION as CONFIG_APP_VERSION

    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
        h.close()
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] %(threadName)s - %(message)s",
        force=True,
    )
    log = logging.getLogger(__name__)
    log.info("Logging reconfigured from config.py.")
except ImportError:
    APP_NAME = "PRIM Application"
    CONFIG_APP_VERSION = "1.0"
    log = logging.getLogger(__name__)
    log.warning("Could not load config.py; using default logging.")

# Suppress verbose matplotlib logs
logging.getLogger("matplotlib").setLevel(logging.WARNING)
QLoggingCategory.setFilterRules("qt.qss.styleSheet=false")


def load_processed_qss(path):
    var_re = re.compile(r"@([A-Za-z0-9_]+):\s*(#[0-9A-Fa-f]{3,8});")
    vars_map, lines = {}, []
    try:
        with open(path) as f:
            for line in f:
                m = var_re.match(line)
                if m:
                    vars_map[m.group(1)] = m.group(2)
                else:
                    for k, v in vars_map.items():
                        line = line.replace(f"@{k}", v)
                    lines.append(line)
        return "".join(lines)
    except Exception as e:
        log.error(f"Error processing QSS {path}: {e}")
        return ""


def _cleanup_ic4():
    if IC4_INITIALIZED and ic4_library_module:
        try:
            log.info("Exiting IC4 library...")
            ic4_library_module.Library.exit()
            log.info("IC4 exited.")
        except Exception as e:
            log.error(f"Error on IC4 exit: {e}")
    else:
        log.info("IC4 not initialized; skipping exit.")


def main_app_entry():
    log.info(f"Starting main_app_entry. IC4_INITIALIZED={IC4_INITIALIZED}")

    # High DPI settings
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    # Set application icon
    base = os.path.dirname(os.path.abspath(__file__))
    icon = os.path.join(base, "ui", "icons", "PRIM.ico")
    if not os.path.exists(icon):
        icon = os.path.join(base, "ui", "icons", "PRIM.png")
    app.setWindowIcon(QIcon(icon))

    # Warn if IC4 not yet initialized
    if not IC4_INITIALIZED:
        if IC4_AVAILABLE:
            QMessageBox.warning(
                None,
                "Camera SDK Problem",
                "ImagingControl4 found but not initialized. Run Camera Setup first.",
            )
        else:
            QMessageBox.warning(
                None,
                "Camera SDK Missing",
                "ImagingControl4 SDK not found. Camera features disabled.",
            )

    # Global exception handler
    def handle_exception(t, v, tb):
        msg = "".join(traceback.format_exception(t, v, tb))
        log.critical(f"Uncaught exception:\n{msg}")
        dlg = QMessageBox(
            QMessageBox.Critical,
            f"{APP_NAME} - Error",
            "An unexpected error occurred.",
            QMessageBox.Ok,
        )
        dlg.setDetailedText(msg)
        dlg.exec_()

    sys.excepthook = handle_exception

    # Load QSS style
    style_path = os.path.join(base, "style.qss")
    if os.path.exists(style_path):
        qss = load_processed_qss(style_path)
        if qss:
            app.setStyleSheet(qss)
            log.info(f"Applied QSS from {style_path}")
        else:
            app.setStyle(QStyleFactory.create("Fusion"))
    else:
        app.setStyle(QStyleFactory.create("Fusion"))

    from main_window import MainWindow

    win = MainWindow()
    win.setWindowTitle(f"{APP_NAME} v{CONFIG_APP_VERSION}")
    win.showMaximized()
    log.info(f"{APP_NAME} started.")

    if IC4_INITIALIZED:
        app.aboutToQuit.connect(_cleanup_ic4)

    sys.exit(app.exec_())


if __name__ == "__main__":
    log = logging.getLogger(__name__)
    log.info(f"Launching prim_app.py; IC4_INITIALIZED={IC4_INITIALIZED}")
    main_app_entry()
