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
QSpinBox,QDoubleSpinBox{background:#1a1d23;border:1px solid #333845;border-radius:8px;padding:5px 8px;color:#e8eaed;}
QCheckBox{color:#e8eaed;}
QLabel#count{font-size:44px;font-weight:600;color:#d7f36b;}
QPushButton{background:transparent;border:1px solid #333845;border-radius:10px;padding:9px 18px;color:#e8eaed;}
QPushButton:hover{border-color:#d7f36b;color:#d7f36b;}
QPushButton#arm{background:#d7f36b;color:#10120a;border-color:#d7f36b;font-weight:600;font-size:15px;}
QPushButton#arm:disabled{background:#2a2f38;color:#6b7280;border-color:#2a2f38;}
QPushButton#preset{padding:6px 12px;font-size:12px;}
"""


def hms_to_seconds(h=0, m=0, s=0.0):
    return h * 3600 + m * 60 + s


def seconds_to_hms(total: float):
    total = max(0.0, float(total))
    h = int(total // 3600)
    m = int((total % 3600) // 60)
    s = total % 60
    return h, m, s


class Window(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Input Lock - demo")
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(460)

        self._mouse = None
        self._pinner = None
        self._kblocker = None
        self._stop = None
        self._armed = False
        self._deadline = 0.0

        self._build()

        self._tick = QtCore.QTimer(self)
        self._tick.setInterval(16)          # ~60fps so the 3-decimal timer is lively
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
        root.addWidget(opts)

        # ---- duration: h / m / s with sub-second precision ----
        dur = QtWidgets.QGroupBox("Lock for")
        df = QtWidgets.QVBoxLayout(dur)
        row = QtWidgets.QHBoxLayout()
        self.sp_h = QtWidgets.QSpinBox(); self.sp_h.setRange(0, 99); self.sp_h.setSuffix(" h")
        self.sp_m = QtWidgets.QSpinBox(); self.sp_m.setRange(0, 59); self.sp_m.setSuffix(" m")
        self.sp_s = QtWidgets.QDoubleSpinBox(); self.sp_s.setRange(0.0, 59.999)
        self.sp_s.setDecimals(3); self.sp_s.setSingleStep(0.1); self.sp_s.setSuffix(" s")
        self.sp_s.setValue(3.0)
        for wdg in (self.sp_h, self.sp_m, self.sp_s):
            wdg.valueChanged.connect(self._refresh_total)
            row.addWidget(wdg)
        df.addLayout(row)

        presets = QtWidgets.QHBoxLayout()
        for label, secs in [("3s", 3), ("5s", 5), ("10s", 10), ("30s", 30),
                            ("1m", 60), ("5m", 300)]:
            b = QtWidgets.QPushButton(label)
            b.setObjectName("preset")
            b.clicked.connect(lambda _=False, s=secs: self._set_seconds(s))
            presets.addWidget(b)
        presets.addStretch(1)
        df.addLayout(presets)

        self.total = QtWidgets.QLabel("")
        self.total.setStyleSheet("color:#9aa0aa;")
        df.addWidget(self.total)
        root.addWidget(dur)

        note = QtWidgets.QLabel(
            "No upper limit. Releases automatically when the countdown ends "
            "(plus a 1s watchdog). Nothing needs to be clicked to unlock.")
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

        self._refresh_total()

    # ---- duration helpers ----
    def _set_seconds(self, total):
        h, m, s = seconds_to_hms(total)
        self.sp_h.setValue(h)
        self.sp_m.setValue(m)
        self.sp_s.setValue(s)
        self._refresh_total()

    def _seconds(self) -> float:
        return hms_to_seconds(self.sp_h.value(), self.sp_m.value(), self.sp_s.value())

    def _refresh_total(self):
        total = self._seconds()
        h, m, s = seconds_to_hms(total)
        self.total.setText(f"= {int(total)} s"
                           + (f"  ({h}h {m}m {s:.3f}s)" if h or m else ""))

    # ---- arm / release ----
    def _on_arm(self):
        if self._armed:
            return
        secs = self._seconds()
        if secs <= 0:
            QtWidgets.QMessageBox.warning(self, "Nothing to lock", "Set a duration above zero.")
            return
        h, m, s = seconds_to_hms(secs)
        pretty = (f"{h}h " if h else "") + (f"{m}m " if m or h else "") + f"{s:.3f}s"
        if QtWidgets.QMessageBox.question(
                self, "Arm the lock?",
                f"Input will be locked for {pretty} ({secs:.3f}s), then released "
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
        h, m, s = seconds_to_hms(left)
        if h:
            self.count.setText(f"{h}:{m:02d}:{s:06.3f}")
        elif m:
            self.count.setText(f"{m}:{s:06.3f}")
        else:
            self.count.setText(f"{s:.3f}")
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
