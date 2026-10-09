"""input_lock_app.py - windowed entry point (no console) for the GUI.

This is the file to freeze into an .exe with PyInstaller using --noconsole, so
the app opens as a normal window with no terminal. Running it directly also
works (python input_lock_app.py).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def main():
    from PySide6 import QtWidgets
    import input_lock_gui as G
    app = QtWidgets.QApplication(sys.argv)
    w = G.Window()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
