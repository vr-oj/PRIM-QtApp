# main_window.py
import sys
import os
import re
import traceback
import logging

# --- Module-level IC4 Initialization Block ---
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
    global IC4_AVAILABLE, IC4_INITIALIZED, ic4_library_module, _ic4_init_has_run_successfully_this_session

    # If we know it succeeded at any point in this Python session, ensure flags reflect that.
    # This handles the case where this function is called again after __main__ already succeeded.
    if _ic4_init_has_run_successfully_this_session:
        IC4_AVAILABLE = True  # It must have been available if init succeeded
        IC4_INITIALIZED = True
        if (
            ic4_library_module is None and IC4_AVAILABLE
        ):  # Re-import ic4 if not set (e.g. in new module scope)
            try:
                import imagingcontrol4 as ic4

                ic4_library_module = ic4
            except ImportError:
                IC4_AVAILABLE = False  # Should not happen if it was available before
                IC4_INITIALIZED = False
        module_log.info(
            "IC4 library previously initialized successfully in this session."
        )
        return

    module_log.info("Attempting IC4 library initialization sequence...")

    try:
        import imagingcontrol4 as ic4

        ic4_library_module = ic4
        IC4_AVAILABLE = True
        module_log.info("imagingcontrol4 library module imported.")
        try:
            ic4.Library.init()
            IC4_INITIALIZED = True
            _ic4_init_has_run_successfully_this_session = (
                True  # Mark success for this session
            )
            module_log.info("ic4.Library.init() called successfully.")

            # ───── Monkey-patch DeviceInfo.__del__ to suppress finalizer RuntimeError ─────
            try:
                import imagingcontrol4.devenum as _dev

                _orig_del = _dev.DeviceInfo.__del__

                def __safe_del(self):
                    try:
                        _orig_del(self)
                    except RuntimeError:
                        # Suppress “Library.init was not called” errors
                        pass

                _dev.DeviceInfo.__del__ = __safe_del
                module_log.info(
                    "Patched DeviceInfo.__del__ to ignore finalizer errors."
                )
            except Exception as _e:
                module_log.warning(f"Could not patch DeviceInfo.__del__: {_e}")
        except Exception as e_init:  # Catch any exception from init()
            err_msg_lower = str(e_init).lower()
            # Check for common phrases indicating already initialized
            if (
                "already called" in err_msg_lower
                or "already been initialized" in err_msg_lower
                or "library is already initialized" in err_msg_lower
            ):
                module_log.warning(
                    f"ic4.Library.init() failed but indicates already initialized: {e_init}. Considering this a success."
                )
                IC4_INITIALIZED = True
                _ic4_init_has_run_successfully_this_session = True  # Mark success
            else:
                module_log.error(
                    f"Failed to initialize imagingcontrol4 library during init(): {e_init}"
                )
                IC4_INITIALIZED = False
    except ImportError:
        module_log.warning("imagingcontrol4 library (ic4) not found on import.")
        IC4_AVAILABLE = False
        IC4_INITIALIZED = False
    except Exception as e_import:
        module_log.error(f"Unexpected error importing imagingcontrol4: {e_import}")
        IC4_AVAILABLE = False
        IC4_INITIALIZED = False

    module_log.info(
        f"IC4 initialization sequence complete. AVAILABLE: {IC4_AVAILABLE}, INITIALIZED: {IC4_INITIALIZED}"
    )


_initialize_ic4_globally()
# --- End of module-level IC4 initialization ---


from PyQt5.QtWidgets import QApplication, QMessageBox, QStyleFactory
from PyQt5.QtCore import Qt, QCoreApplication, QLoggingCategory


try:
    from config import APP_NAME, LOG_LEVEL, APP_VERSION as CONFIG_APP_VERSION

    root_logger = logging.getLogger()
    for handler_item in root_logger.handlers[:]:  # Use different var name
        root_logger.removeHandler(handler_item)
        handler_item.close()

    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] %(threadName)s - %(message)s",
        force=True,
    )
    log = logging.getLogger(__name__)
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
    log.info(
        f"main_app_entry started. IC4_AVAILABLE: {IC4_AVAILABLE}, IC4_INITIALIZED: {IC4_INITIALIZED}"
    )

    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    if not IC4_INITIALIZED:
        if IC4_AVAILABLE:
            QMessageBox.warning(
                None,
                "Camera SDK Problem",
                f"TIS camera SDK (imagingcontrol4) was found but could not be initialized.\n"
                "TIS camera functionality will be unavailable. Please check logs for details.",
            )
        else:
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
    log.info(
        f"Running prim_app.py as __main__. IC4_INITIALIZED at this point: {IC4_INITIALIZED}"
    )
    main_app_entry()
