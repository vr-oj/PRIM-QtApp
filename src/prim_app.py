import sys
from PyQt5.QtWidgets import QApplication
from main_window import MainWindow

def main():
    app = QApplication(sys.argv)

    # Load dark style
    try:
        with open("style.qss", "r") as f:
            app.setStyleSheet(f.read())
    except Exception:
        pass

    w = MainWindow()
    w.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
