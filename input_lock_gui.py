"""input_lock_gui.py - a small GUI for the input_lock demo.

Why a GUI version has to be time-based: once the keyboard and/or mouse are
locked, the app's own buttons and hotkeys are unreachable, so the escape cannot
depend on the user clicking "stop". The only safe design is a self-releasing
time box, kept honest by three independent guarantees (all inherited from
input_lock.py):

  1. a countdown releases at the chosen duration, with no user input;
  2. a watchdog releases at duration + 1s, even if the UI loop dies;
  3. killing the process drops the hooks (and Windows resets ClipCursor).

Ctrl+C in the console still works for the mouse-only case; for the keyboard
case the countdown is the way out. Nothing here blocks the keyboard
irreversibly - the release path never needs the locked device.

Run:  python input_lock_gui.py
"""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

import input_lock as L  # noqa: E402   (reuse the vetted lock primitives)

STYLE = """
QWidget{background:#0c0d10;color:#e8eaed;font-size:13px;}
QGroupBox{border:1px solid #262a32;border-radius:10px;margin-top:14px;padding:12px;}
QGroupBox::title{subcontrol-origin:margin;left:12px;color:#9aa0aa;}
QSpinBox{background:#1a1d23;border:1px solid #333845;border-radius:8px;padding:5px 8px;color:#e8eaed;}
QCheckBox{color:#e8eaed;}
QLabel#count{font-size:44px;font-weight:600;color:#d7f36b;}
QPushButton{background:transparent;border:1px solid #333845;border-radius:10px;padding:9px 18px;color:#e8eaed;}
QPushButton:hover{border-color:#d7f36b;color:#d7f36b;}
QPushButton#arm{background:#d7f36b;color:#10120a;border-color:#d7f36b;font-weight:600;font-size:15px;}
QPushButton#arm:disabled{background:#2a2f38;color:#6b7280;border-color:#2a2f38;}
"""

MAX_SECONDS = 60      # hard cap so a typo cannot lock the machine for long


class Window(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Input Lock - demo")
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(420)

        self._mouse = None
        self._pinner = None
        self._kblocker = None
        self._stop = None
        self._armed = False
        self._deadline = 0.0

        self._build()

        self._tick = QtCore.QTimer(self)
        self._tick.setInterval(100)
        self._tick.timeout.connect(self._on_tick)

    def _build(self):
        root = QtWidgets.QVBoxLayout(self)

        opts = QtWidgets.QGroupBox("What to lock")
        form = QtWidgets.QFormLayout(opts)

        self.cb_mouse = QtWidgets.QCheckBox("Mouse buttons and wheel")
        self.cb_mouse.setChecked(True)
        self.cb_move = QtWidgets.QCheckBox("Freeze pointer movement (hard, via ClipCursor)")
        self.cb_move.setChecked(True)
        self.cb_keys = QtWidgets.QCheckBox("Keyboard (all keys; only the timer releases)")
        form.addRow(self.cb_mouse)
        form.addRow(self.cb_move)
        form.addRow(self.cb_keys)

        self.secs = QtWidgets.QSpinBox()
        self.secs.setRange(1, MAX_SECONDS)
        self.secs.setValue(3)
        self.secs.setSuffix("  s")
        form.addRow("Lock for", self.secs)
        root.addWidget(opts)

        note = QtWidgets.QLabel(
            "Releases automatically when the countdown ends (plus a 1s watchdog). "
            "Nothing needs to be clicked to unlock.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#9aa0aa;")
        root.addWidget(note)

        self.count = QtWidgets.QLabel("--")
        self.count.setObjectName("count")
        self.count.setAlignment(QtCore.Qt.AlignCenter)
        root.addWidget(self.count)

        self.arm = QtWidgets.QPushButton("ARM")
        self.arm.setObjectName("arm")
        self.arm.clicked.connect(self._on_arm)
        root.addWidget(self.arm)

        self.status = QtWidgets.QLabel("idle")
        self.status.setStyleSheet("color:#9aa0aa;")
        self.status.setAlignment(QtCore.Qt.AlignCenter)
        root.addWidget(self.status)

    # ---- arm / release ----
    def _on_arm(self):
        if self._armed:
            return
        secs = self.secs.value()
        if QtWidgets.QMessageBox.question(
                self, "Arm the lock?",
                f"Input will be locked for {secs} seconds, then released "
                f"automatically.\n\nKeep this window open.\n\nProceed?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
            return

        kinds = {"all"} if self.cb_mouse.isChecked() else set()
        self._mouse = L.MouseBlocker(kinds) if kinds else None
        self._pinner = L.CursorPinner() if self.cb_move.isChecked() else None
        self._kblocker = L.KeyboardBlocker([0]) if self.cb_keys.isChecked() else None
        self._stop = threading.Event()

        if self._mouse and not self._mouse.install():
            self.status.setText("mouse hook failed")
            return
        if self._mouse:
            threading.Thread(target=self._mouse.run_until, args=(self._stop,), daemon=True).start()
        if self._pinner:
            self._pinner.start()
        if self._kblocker:
            self._kblocker.start()

        self._armed = True
        self.arm.setEnabled(False)
        self.arm.setText("ARMED")
        self._deadline = time.monotonic() + secs
        self._tick.start()

        # watchdog: release at seconds + 1 no matter what
        threading.Thread(target=self._watchdog, args=(secs + 1.0,), daemon=True).start()

    def _watchdog(self, after):
        time.sleep(after)
        QtCore.QMetaObject.invokeMethod(self, "_release", QtCore.Qt.QueuedConnection)

    @QtCore.Slot()
    def _release(self):
        if not self._armed:
            return
        self._armed = False
        self._tick.stop()
        try:
            if self._pinner:
                self._pinner.stop()
            if self._kblocker:
                self._kblocker.stop()
            if self._mouse:
                self._mouse.stop()
                self._mouse.uninstall()
            if self._stop:
                self._stop.set()
        except Exception:
            pass
        self.arm.setEnabled(True)
        self.arm.setText("ARM")
        self.count.setText("--")
        self.status.setText("released")

    def _on_tick(self):
        left = self._deadline - time.monotonic()
        if left <= 0:
            self._release()
            return
        self.count.setText(f"{left:0.1f}")
        self.status.setText("LOCKED - releases automatically")

    def closeEvent(self, e):
        # closing the window must never leave a lock behind
        self._release()
        e.accept()


def main():
    app = QtWidgets.QApplication(sys.argv)
    w = Window()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
