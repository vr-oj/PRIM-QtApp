# PRIM-QTAPP/prim_app/prim_app.py
import sys
import os
import re
import traceback
import logging
from PyQt5.QtWidgets import QApplication, QMessageBox, QStyleFactory
from PyQt5.QtCore import Qt, QCoreApplication, QLoggingCategory
from PyQt5.QtGui import QIcon

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
    ic4_library_module = ic4
    module_log.info("imagingcontrol4 module imported successfully")
except ImportError:
    IC4_AVAILABLE = False
    ic4_library_module = None
    module_log.error(
        "Could not import imagingcontrol4 — camera functionality will be disabled."
    )

# === IC4 Initialization Flags ===
IC4_LIBRARY_INITIALIZED = False
IC4_GENTL_SYSTEM_CONFIGURED = False


def initialize_ic4_with_cti(cti_path: str):
    """
    Persist CTI path, update GENICAM_GENTL64_PATH, and initialize IC4 idempotently.
    """
    global IC4_LIBRARY_INITIALIZED, IC4_GENTL_SYSTEM_CONFIGURED, IC4_AVAILABLE

    # 1) Persist choice
    try:
        save_app_setting(SETTING_CTI_PATH, cti_path)
    except Exception as e:
        module_log.warning(f"Failed to save CTI path setting: {e}")

    # 2) Add CTI folder to GenTL path
    cti_dir = os.path.dirname(cti_path)
    env_key = "GENICAM_GENTL64_PATH"
    existing = os.environ.get(env_key, "")
    paths = existing.split(os.pathsep) if existing else []
    if cti_dir not in paths:
        new_paths = os.pathsep.join([cti_dir] + paths)
        os.environ[env_key] = new_paths
        module_log.info(f"Set {env_key}={new_paths}")

    # 3) Initialize the IC4 library only once
    try:
        if not IC4_LIBRARY_INITIALIZED:
            ic4.Library.init()
            module_log.info("ic4.Library.init() succeeded")
        else:
            module_log.debug("ic4.Library.init() already called; skipping")
    except RuntimeError as e:
        msg = str(e).lower()
        if "already called" in msg:
            module_log.debug("Treating repeated init as success")
        else:
            module_log.error(f"Unexpected init error: {e}")
            raise

    # 4) Flip both flags
    IC4_LIBRARY_INITIALIZED = True
    IC4_GENTL_SYSTEM_CONFIGURED = True
    IC4_AVAILABLE = True


def is_ic4_fully_initialized():
    """Checks if IC4 init and CTI configured."""
    return IC4_LIBRARY_INITIALIZED and IC4_GENTL_SYSTEM_CONFIGURED


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
        force=True,
    )
    log = logging.getLogger(__name__)
    log.info(f"Logging configured: {LOG_LEVEL.upper()}")
except ImportError:
    APP_NAME = "PRIM Application (Default)"
    CONFIG_APP_VERSION = "1.0d"
    log = logging.getLogger(__name__)
    if not log.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] %(threadName)s - %(message)s",
        )
    log.warning("utils.config missing: using defaults.")

# Suppress noisy logs
logging.getLogger("matplotlib").setLevel(logging.WARNING)
QLoggingCategory.setFilterRules("qt.qss.styleSheet=false")


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
                    for name, val in vars_map.items():
                        line = line.replace(f"@{name}", val)
                    lines.append(line)
        return "".join(lines)
    except Exception as e:
        log.error(f"Error loading QSS {path}: {e}")
        return ""


def _cleanup_ic4():
    global IC4_LIBRARY_INITIALIZED, IC4_GENTL_SYSTEM_CONFIGURED
    if IC4_LIBRARY_INITIALIZED and ic4_library_module:
        try:
            log.info("Exiting IC4 library...")
            ic4_library_module.Library.exit()
            IC4_LIBRARY_INITIALIZED = False
            IC4_GENTL_SYSTEM_CONFIGURED = False
            log.info("IC4 library exited.")
        except Exception as e:
            log.warning(f"Error during IC4 exit: {e}")
    else:
        log.info("IC4 not initialized: skipping cleanup.")


def attempt_saved_ic4_init():
    if not APP_SETTINGS_AVAILABLE:
        log.warning("Settings unavailable: cannot auto-init CTI.")
        return
    path = load_app_setting(SETTING_CTI_PATH)
    if path and os.path.exists(path):
        module_log.info(f"Auto-init CTI: {path}")
        try:
            initialize_ic4_with_cti(path)
            if is_ic4_fully_initialized():
                module_log.info("IC4 fully initialized.")
        except Exception as e:
            module_log.error(f"Auto-init error: {e}")
    else:
        module_log.info("No saved CTI; user will be prompted.")


def main_app_entry():
    log.info(
        f"App start: IC4_AVAILABLE={IC4_AVAILABLE}, INIT={IC4_LIBRARY_INITIALIZED}, CTI_CFG={IC4_GENTL_SYSTEM_CONFIGURED}"
    )
    attempt_saved_ic4_init()
    # High DPI
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    icon_dir = os.path.join(base_dir, "ui", "icons")
    ico = os.path.join(icon_dir, "PRIM.ico")
    png = os.path.join(icon_dir, "PRIM.png")
    icon = QIcon()
    if os.path.exists(ico):
        icon.addFile(ico)
    elif os.path.exists(png):
        icon.addFile(png)
    if icon and not icon.isNull():
        app.setWindowIcon(icon)

    if not IC4_AVAILABLE and not os.environ.get("PRIM_APP_TESTING_NO_IC4"):
        QMessageBox.critical(
            None,
            f"{APP_NAME} - Camera SDK Missing",
            "The 'imagingcontrol4' Python module was not found. Camera features disabled.",
        )

    def custom_exception_handler(exc_type, value, tb):
        msg = "".join(traceback.format_exception(exc_type, value, tb))
        log.critical(f"UNCAUGHT EXCEPTION:\n{msg}")
        dlg = QMessageBox(
            QMessageBox.Critical,
            f"{APP_NAME} - Critical Error",
            "An unhandled error occurred.",
            QMessageBox.Ok,
        )
        dlg.setDetailedText(msg)
        dlg.exec_()

    sys.excepthook = custom_exception_handler

    style_path = os.path.join(base_dir, "style.qss")
    if os.path.exists(style_path):
        qss = load_processed_qss(style_path)
        if qss:
            app.setStyleSheet(qss)
        else:
            app.setStyle(QStyleFactory.create("Fusion"))
    else:
        app.setStyle(QStyleFactory.create("Fusion"))

    from main_window import MainWindow

    main_win = MainWindow()
    version = CONFIG_APP_VERSION if "CONFIG_APP_VERSION" in globals() else "1.0"
    main_win.setWindowTitle(f"{APP_NAME} v{version}")
    main_win.showMaximized()

    if IC4_LIBRARY_INITIALIZED:
        app.aboutToQuit.connect(_cleanup_ic4)

    code = app.exec_()
    sys.exit(code)


if __name__ == "__main__":
    launcher_log = logging.getLogger("prim_app_launcher")
    if not launcher_log.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        )
    launcher_log.info(
        f"Launching prim_app.py. IC4_INITED={IC4_LIBRARY_INITIALIZED}, CTI_CFG={IC4_GENTL_SYSTEM_CONFIGURED}"
    )
    main_app_entry()
