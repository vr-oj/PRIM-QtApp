import sys
import os
import traceback
import logging
from PyQt5.QtWidgets import QApplication, QMessageBox, QStyleFactory
from PyQt5.QtCore import Qt, QCoreApplication # Added QCoreApplication for setAttribute

# Attempt to import config for early logging setup
try:
    from config import APP_NAME, LOG_LEVEL
    numeric_log_level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(level=numeric_log_level,
                        format='%(asctime)s - %(levelname)s [%(name)s:%(lineno)d] %(threadName)s - %(message)s')
    log = logging.getLogger(__name__)
except ImportError as e:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    log = logging.getLogger(__name__)
    log.warning(f"Could not import from config.py: {e}. Using default INFO level for logging.")
    APP_NAME = "PRIM Application" # Fallback app name


def main_app_entry():
    # It's good practice for QApplication to be the first Qt object created
    # This handles high DPI scaling better if done early.
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True) # Use QCoreApplication
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)    # Use QCoreApplication

    app = QApplication(sys.argv)

    try:
        # Global exception hook
        def handle_exception(exc_type, exc_value, exc_traceback):
            msg_list = traceback.format_exception(exc_type, exc_value, exc_traceback)
            error_msg_detailed = "".join(msg_list)
            log.critical(f"UNCAUGHT EXCEPTION:\n{error_msg_detailed}")

            error_dialog = QMessageBox()
            error_dialog.setIcon(QMessageBox.Critical)
            error_dialog.setWindowTitle(f"{APP_NAME} - Critical Error")
            error_dialog.setText("An unexpected error occurred and the application may need to close.")
            error_dialog.setInformativeText("Please check the console output or log file for more details.")
            error_dialog.exec_()

        sys.excepthook = handle_exception

        # Load QSS stylesheet
        base_dir = os.path.dirname(os.path.abspath(__file__))
        qss_file_path = os.path.join(base_dir, "style.qss")

        if os.path.exists(qss_file_path):
            try:
                with open(qss_file_path, "r") as f_qss:
                    app.setStyleSheet(f_qss.read())
                log.info(f"Successfully loaded stylesheet: {qss_file_path}")
            except Exception as e_qss:
                log.warning(f"Could not load or apply style.qss from {qss_file_path}: {e_qss}")
                app.setStyle(QStyleFactory.create("Fusion"))
        else:
            log.warning(f"Stylesheet style.qss not found at {qss_file_path}. Using default Fusion style.")
            app.setStyle(QStyleFactory.create("Fusion"))


        from main_window import MainWindow

        window = MainWindow()
        window.show()
        log.info(f"{APP_NAME} started successfully.")
        sys.exit(app.exec_())

    except SystemExit:
        log.info("Application exiting via SystemExit.")
    except Exception as e_startup:
        detailed_error = traceback.format_exc()
        log.critical(f"CRITICAL STARTUP ERROR for {APP_NAME}:\n{detailed_error}")
        try:
            QMessageBox.critical(None, f"{APP_NAME} - Fatal Startup Error",
                                 f"A critical error occurred during application startup and it cannot continue:\n\n{str(e_startup)}\n\n"
                                 "Please check the console or log files for detailed information.")
        except Exception as e_msgbox:
            print(f"CRITICAL STARTUP ERROR (QMessageBox failed: {e_msgbox}):\n{detailed_error}")
        sys.exit(1)

if __name__ == "__main__":
    main_app_entry()