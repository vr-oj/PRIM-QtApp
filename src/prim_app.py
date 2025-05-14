import sys, os, traceback
from PyQt5.QtWidgets import QApplication

def main():
    try:
        app = QApplication(sys.argv)

        # 6. Install global exception hook so Qt signals also get caught
        def handle_exception(exc_type, exc_value, exc_traceback):
            msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            print("Uncaught exception:\n", msg)
        sys.excepthook = handle_exception

        # 2. Use absolute path to your QSS
        base = os.path.dirname(__file__)
        qss_file = os.path.join(base, "style.qss")
        if os.path.exists(qss_file):
            with open(qss_file, "r") as f:
                app.setStyleSheet(f.read())
        else:
            print(f"Warning: style.qss not found at {qss_file}")

        from main_window import MainWindow
        window = MainWindow()
        window.show()
        sys.exit(app.exec_())

    except Exception:
        # catch any import‑time or init error and print it
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
