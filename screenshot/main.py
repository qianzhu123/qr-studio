"""main.py - QR Shot: right-drag screenshot tool with annotation and QR decode.

TRIGGER: the RIGHT mouse button only, detected by POLLING GetAsyncKeyState and
GetCursorPos. There is NO low-level mouse hook, so the tool never intercepts or
blocks any input and therefore cannot freeze the mouse or keyboard. A plain
right click is completely untouched (its context menu still appears).

Run visibly (with a console) so it is trivially killable: close the console
window, use the tray Quit, or end the process in Task Manager. A stuck overlay
is also self-healed by a watchdog.

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

from overlay import Overlay  # noqa: E402
from poll_watch import RightDragWatcher  # noqa: E402

try:
    from qr_decode import decode_image, trace_redirects
except Exception:
    decode_image = trace_redirects = None

OVERLAY_TIMEOUT_MS = 45000      # self-close a stuck overlay


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
        # Right-button DRAG, detected by POLLING (no low-level hook). This can
        # never intercept or block input, so it cannot wedge the mouse. The
        # right button is otherwise untouched; a plain click still opens the
        # normal context menu.
        self.watcher = RightDragWatcher(threshold=10)
        self.watcher.down.connect(self.on_down)
        self.watcher.move.connect(self.on_move)
        self.watcher.up.connect(self.on_up)
        self._overlay_timer = QtCore.QTimer()
        self._overlay_timer.setSingleShot(True)
        self._overlay_timer.timeout.connect(self._overlay_timeout)

    def _overlay_timeout(self):
        if self.overlay and self.overlay.isVisible():
            self.overlay.close_overlay()

    # ---- right-drag -> overlay ----
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
        self._overlay_timer.start(OVERLAY_TIMEOUT_MS)

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
        self.tray.setToolTip("QR Shot - right-drag to capture")
        menu = QtWidgets.QMenu()
        menu.addAction("Capture now (or right-drag)", self.capture)
        menu.addAction("Decode from clipboard", self.decode_clipboard)
        self.act_pause = menu.addAction("Pause watching")
        self.act_pause.setCheckable(True)
        self.act_pause.triggered.connect(lambda on: self.watcher.set_enabled(not on))
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
            self._overlay_timer.stop()
            self.watcher.set_enabled(False)
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
    # Make the console unmistakable and closable: closing this window (X) ends
    # the tool immediately, which works even if the overlay is stuck.
    try:
        ctypes.windll.kernel32.SetConsoleTitleW("QR SHOT - close this window to quit")
    except Exception:
        pass
    print("QR Shot running. Close THIS window to quit. Right-drag to capture.", flush=True)
    qapp = QtWidgets.QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    App(qapp)
    sys.exit(qapp.exec())


if __name__ == "__main__":
    main()
