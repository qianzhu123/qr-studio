"""main.py - QR Shot: hotkey screenshot tool with annotation and QR decode.

Trigger: a GLOBAL HOTKEY (default Ctrl+Alt+Q) registered with Win32
RegisterHotKey. There is NO low-level mouse hook, so this can never stall or
freeze mouse/keyboard input.

Flow: press the hotkey -> a frozen full-screen overlay appears -> drag with the
LEFT mouse button to select a region -> the raw region is auto-copied ->
annotate -> Copy / Save / Pin / Decode. Click outside the selection to hide the
toolbar; Esc cancels.

Run:  python screenshot/main.py
"""
from __future__ import annotations

import ctypes
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
sys.path.insert(0, HERE)

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

import hotkey as hotkey_mod  # noqa: E402
from overlay import Overlay  # noqa: E402
from poll_watch import RightDragWatcher  # noqa: E402

try:
    from qr_decode import decode_image, trace_redirects
except Exception:
    decode_image = trace_redirects = None

HOTKEY = os.environ.get("QR_SHOT_HOTKEY", "Ctrl+Alt+Q")


def set_dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class DecodePopup(QtWidgets.QWidget):
    """Small always-on-top result card shown after decoding a selection."""

    def __init__(self, res: dict, pixmap=None):
        super().__init__()
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint |
                            QtCore.Qt.Tool)
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget{background:#14161b;border:1px solid #333845;border-radius:12px;}"
            "QLabel{color:#e8eaed;} QPushButton{color:#e8eaed;background:transparent;"
            "border:1px solid #333845;border-radius:8px;padding:5px 10px;}"
            "QPushButton:hover{border-color:#d7f36b;color:#d7f36b;}")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        title = QtWidgets.QLabel("QR Shot")
        title.setStyleSheet("color:#d7f36b;font-weight:600;")
        lay.addWidget(title)

        self.url = ""
        if not res or not res.get("text"):
            lay.addWidget(QtWidgets.QLabel("No code found in the selection."))
        else:
            self.url = res["text"] if str(res["text"]).startswith(("http://", "https://")) else ""
            meta = res.get("meta") or {}
            fmt = meta.get("format") or ""
            head = (res.get("kind") or "") + (f"  ·  {fmt}" if fmt else "")
            k = QtWidgets.QLabel(head)
            k.setStyleSheet("color:#9aa0aa;font-size:12px;")
            lay.addWidget(k)
            body = QtWidgets.QLabel(str(res["text"]))
            body.setWordWrap(True)
            body.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            body.setMaximumWidth(460)
            lay.addWidget(body)
            if res.get("links") and len(res["links"]) > 1:
                nested = QtWidgets.QLabel("nested: " + res["links"][1])
                nested.setStyleSheet("color:#9aa0aa;font-size:12px;")
                nested.setWordWrap(True)
                nested.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
                lay.addWidget(nested)

        row = QtWidgets.QHBoxLayout()
        for name, fn in [("Copy", self._copy), ("Trace", self._trace)]:
            b = QtWidgets.QPushButton(name)
            b.clicked.connect(fn)
            row.addWidget(b)
            if name == "Trace" and not self.url:
                b.setEnabled(False)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.close)
        row.addWidget(close)
        lay.addLayout(row)

        self.trace_label = QtWidgets.QLabel("")
        self.trace_label.setStyleSheet("color:#9aa0aa;font-size:12px;")
        self.trace_label.setWordWrap(True)
        lay.addWidget(self.trace_label)

        self.adjustSize()
        self._place_near_cursor()

    def _place_near_cursor(self):
        p = QtGui.QCursor.pos()
        scr = QtGui.QGuiApplication.screenAt(p) or QtGui.QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        x = min(p.x() + 16, g.right() - self.width() - 8)
        y = min(p.y() + 16, g.bottom() - self.height() - 8)
        self.move(max(g.left() + 8, x), max(g.top() + 8, y))

    def _copy(self):
        QtWidgets.QApplication.clipboard().setText(self.url or "")

    def _trace(self):
        if not self.url:
            return
        self.trace_label.setText("tracing (HEAD only)...")
        QtWidgets.QApplication.processEvents()
        try:
            chain = trace_redirects(self.url)
            self.trace_label.setText("\n".join(
                f"{h.get('status','')}  {h.get('location','')}".strip() for h in chain) or "no redirects")
        except Exception as e:
            self.trace_label.setText(f"trace failed: {e}")


class App(QtCore.QObject):
    def __init__(self, qapp: QtWidgets.QApplication):
        super().__init__()
        self.q = qapp
        self.overlay = None
        self.popup = None
        self._build_tray()
        # Two hook-free triggers, both safe:
        #  - a global hotkey via RegisterHotKey
        #  - right-button DRAG detected by POLLING GetAsyncKeyState/GetCursorPos
        # Neither installs a low-level hook, so neither can stall input.
        self.hotkey = hotkey_mod.Hotkey(HOTKEY)
        self.hotkey.start()
        self.watcher = RightDragWatcher(threshold=10)
        self.watcher.down.connect(self.on_down)
        self.watcher.move.connect(self.on_move)
        self.watcher.up.connect(self.on_up)
        self._timer = QtCore.QTimer()
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        if not self.hotkey.ok:
            QtCore.QTimer.singleShot(600, lambda: self.tray.showMessage(
                "QR Shot", f"Hotkey {HOTKEY} could not be registered (already in use?)."))

    def _poll(self):
        try:
            fired = self.hotkey.fired.get_nowait()
        except Exception:
            return
        if fired:
            self.capture()

    # ---- hook-free right-drag -> overlay ----
    def _logical(self, x, y):
        dpr = 1.0
        for s in QtGui.QGuiApplication.screens():
            if s.geometry().contains(x, y):
                dpr = s.devicePixelRatio() or 1.0
                break
        return int(x / dpr), int(y / dpr)

    def on_down(self, x, y):
        if self.overlay is not None and self.overlay.isVisible():
            return
        self.capture()
        lx, ly = self._logical(x, y)
        self.overlay.begin_drag(lx, ly)

    def on_move(self, x, y):
        if self.overlay and self.overlay.isVisible():
            lx, ly = self._logical(x, y)
            self.overlay.update_drag(lx, ly)

    def on_up(self, x, y):
        if self.overlay and self.overlay.isVisible():
            lx, ly = self._logical(x, y)
            self.overlay.hook_release(lx, ly)

    # ---- tray ----
    def _build_tray(self):
        self.tray = QtWidgets.QSystemTrayIcon(self._make_icon())
        self.tray.setToolTip(f"QR Shot - {HOTKEY} to capture")
        menu = QtWidgets.QMenu()
        menu.addAction(f"Capture  ({HOTKEY})", self.capture)
        menu.addAction("Decode from clipboard", self.decode_clipboard)
        menu.addSeparator()
        menu.addAction("Quit", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.show()

    def _make_icon(self):
        pm = QtGui.QPixmap(64, 64)
        pm.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor("#d7f36b"))
        p.drawRoundedRect(4, 4, 56, 56, 12, 12)
        p.setBrush(QtGui.QColor("#10120a"))
        for (x, y) in [(14, 14), (38, 14), (14, 38)]:
            p.drawRect(x, y, 12, 12)
        p.drawRect(38, 38, 12, 12)
        p.end()
        return QtGui.QIcon(pm)

    # ---- capture ----
    def capture(self):
        if self.overlay is not None and self.overlay.isVisible():
            self.overlay.close_overlay()
        self.overlay = Overlay(self.handle_decode)
        self.overlay.finished.connect(self._on_overlay_done)
        self.overlay.show()

    def _on_overlay_done(self):
        self.overlay = None

    def handle_decode(self, bgr, pixmap):
        if self.overlay:
            self.overlay.close_overlay()
        res = None
        if decode_image is not None:
            try:
                res = decode_image(bgr)
            except Exception as e:
                res = {"text": None, "kind": f"decode error: {e}"}
        self.popup = DecodePopup(res)
        self.popup.show()

    def decode_clipboard(self):
        if decode_image is None:
            return
        import numpy as np
        import cv2
        from PIL import ImageGrab
        img = ImageGrab.grabclipboard()
        if img is None or not hasattr(img, "convert"):
            self.tray.showMessage("QR Shot", "Clipboard has no image.")
            return
        bgr = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
        self.popup = DecodePopup(decode_image(bgr))
        self.popup.show()

    def quit(self):
        try:
            self._timer.stop()
            self.hotkey.stop()
            self.hotkey.join(timeout=1.0)
        except Exception:
            pass
        self.q.quit()


def _single_instance():
    k = ctypes.windll.kernel32
    k.CreateMutexW(None, False, "Global\\QRShotSingleInstance_v2")
    return k.GetLastError() != 183


def main():
    if not _single_instance():
        sys.exit(0)
    set_dpi_aware()
    qapp = QtWidgets.QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    App(qapp)
    sys.exit(qapp.exec())


if __name__ == "__main__":
    main()
