import sys
from PyQt5.QtWidgets import QApplication
from main_window import MainWindow

def main():
    app = QApplication(sys.argv)

    # ▶️ load your dark stylesheet
    try:
        with open("style.qss") as f:
            app.setStyleSheet(f.read())
    except Exception as e:
        print("⚠️  Could not load style.qss:", e)

    w = MainWindow()
    w.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
