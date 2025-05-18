import sys
import os
import traceback
import logging

from PyQt5.QtWidgets import QApplication, QMessageBox, QStyleFactory
from PyQt5.QtCore import Qt, QCoreApplication

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
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )

log = logging.getLogger(__name__)

# ─── Optional TIS camera library ────────────────────────────────────────────
try:
    import imagingcontrol4 as ic4

    IC4_AVAILABLE = True
    log.info("imagingcontrol4 library found.")
except ImportError:
    IC4_AVAILABLE = False
    log.warning("imagingcontrol4 library not found; camera disabled.")


# ─── Application entry point ─────────────────────────────────────────────────
def main_app_entry():
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
            log.info("imagingcontrol4 Library initialized.")
        except Exception as e:
            log.error(f"Failed to init imagingcontrol4: {e}")

    # global exception handler
    def _handle_exception(exc_type, exc_value, exc_tb):
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log.critical("UNCAUGHT EXCEPTION:\n%s", msg)
        dlg = QMessageBox(
            QMessageBox.Critical,
            f"{APP_NAME} - Error",
            "An unexpected error occurred.",
            QMessageBox.Ok,
        )
        dlg.setDetailedText(msg)
        dlg.exec_()

    sys.excepthook = _handle_exception

    # load stylesheet or fall back to Fusion
    style_path = os.path.join(os.path.dirname(__file__), "style.qss")
    if os.path.exists(style_path):
        try:
            with open(style_path) as f:
                app.setStyleSheet(f.read())
            log.info("Loaded style.qss")
        except Exception as e:
            log.warning("Failed to apply style.qss: %s", e)
            app.setStyle(QStyleFactory.create("Fusion"))
    else:
        log.warning("style.qss not found, using Fusion")
        app.setStyle(QStyleFactory.create("Fusion"))

    # import MainWindow late to avoid circular dependencies
    from main_window import MainWindow

    window = MainWindow()
    window.show()
    log.info("%s started.", APP_NAME)

    # clean up ic4 on quit
    if IC4_AVAILABLE:

        def _cleanup_ic4():
            try:
                ic4.Library.exit()
                log.info("imagingcontrol4 Library exited.")
            except Exception as e:
                log.error("Error exiting imagingcontrol4: %s", e)

        app.aboutToQuit.connect(_cleanup_ic4)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main_app_entry()
