"""main.py - QR Shot: right-drag screenshot tool with annotations and QR decode.

- Tray-resident, no main window.
- Right-button DRAG on screen opens a freezed selection overlay (a plain right
  click still shows the normal context menu).
- Annotate, then copy / save / pin / decode as QR.
- Decoding is local (qr-studio's qr_decode), no server needed.

Run:  python screenshot/main.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
sys.path.insert(0, HERE)

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

import mouse_hook  # noqa: E402
from overlay import Overlay  # noqa: E402

try:
    from qr_decode import decode_image, trace_redirects
except Exception:
    decode_image = trace_redirects = None


def _dpr_at(x: int, y: int) -> float:
    """Device pixel ratio of the screen containing a physical point."""
    for s in QtGui.QGuiApplication.screens():
        g = s.geometry()
        dpr = s.devicePixelRatio()
        lg = QtCore.QRectF(g.x() * dpr, g.y() * dpr, g.width() * dpr, g.height() * dpr)
        if lg.contains(x, y):
            return dpr
    return QtGui.QGuiApplication.primaryScreen().devicePixelRatio()


class DecodePopup(QtWidgets.QWidget):
    """Small always-on-top result card shown after decoding a selection."""

    def __init__(self, res: dict, pixmap=None):
        super().__init__()
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint |
                            QtCore.Qt.Tool)
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget{background:#14161b;border:1px solid #333845;border-radius:12px;}"
            "QLabel{color:#e8eaed;} QLabel.k{color:#9aa0aa;} "
            "QPushButton{color:#e8eaed;background:transparent;border:1px solid #333845;"
            "border-radius:8px;padding:5px 10px;} QPushButton:hover{border-color:#d7f36b;color:#d7f36b;}")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        title = QtWidgets.QLabel("QR Shot")
        title.setStyleSheet("color:#d7f36b;font-weight:600;")
        lay.addWidget(title)

        if not res or not res.get("text"):
            lay.addWidget(QtWidgets.QLabel("No code found in the selection."))
            self.url = ""
        else:
            self.url = res["text"] if str(res["text"]).startswith(("http://", "https://")) else ""
            meta = res.get("meta") or {}
            fmt = meta.get("format") or ""
            kind = res.get("kind") or ""
            head = f"{kind}" + (f"  ·  {fmt}" if fmt else "")
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
            if name == "Trace" and not getattr(self, "url", ""):
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
        text = ""
        if hasattr(self, "url") and self.url:
            text = self.url
        QtWidgets.QApplication.clipboard().setText(text)

    def _trace(self):
        if not getattr(self, "url", ""):
            return
        self.trace_label.setText("tracing (HEAD only)...")
        QtWidgets.QApplication.processEvents()
        try:
            chain = trace_redirects(self.url)
            self.trace_label.setText("\n".join(f"{h.get('status','')}  {h.get('location','')}".strip()
                                               for h in chain) or "no redirects")
        except Exception as e:
            self.trace_label.setText(f"trace failed: {e}")


class App(QtCore.QObject):
    def __init__(self, qapp: QtWidgets.QApplication):
        super().__init__()
        self.q = qapp
        self.overlay = None
        self.popup = None
        self._enabled = True
        self._build_tray()
        # Observe-only hook on its own thread; Qt polls the event queue. The
        # hook never touches Qt directly, so mouse input can never stall.
        # swallow=True hides only the RIGHT-DRAG events from other apps, so a
        # captured screen does not also pop a context menu or select text. A
        # plain right click is never swallowed (threshold=10).
        self.hook = mouse_hook.MouseHook(swallow=True, threshold=10)
        self.hook.start()
        self._timer = QtCore.QTimer()
        self._timer.setInterval(15)
        self._timer.timeout.connect(self._pump)
        self._timer.start()
        # Watchdog: never let an overlay stay open more than 60s (self-heal if
        # a drag is interrupted by a screen-lock, RDP drop, etc.).
        self._watchdog = QtCore.QTimer()
        self._watchdog.setInterval(2000)
        self._watchdog.timeout.connect(self._check_overlay)
        self._watchdog.start()

    def _check_overlay(self):
        if self.overlay is not None and self.overlay.isVisible():
            self._overlay_age = getattr(self, "_overlay_age", 0) + 2
            if self._overlay_age > 60:
                self._overlay_age = 0
                self.overlay.close_overlay()
        else:
            self._overlay_age = 0

    def _pump(self):
        import time
        now = time.monotonic()
        while True:
            try:
                name, x, y, ts = self.hook.events.get_nowait()
            except Exception:
                break
            if now - ts > 2.0:      # stale backlog (e.g. after a pause): skip
                continue
            if not self._enabled:
                continue
            if name == "down":
                self.on_down(x, y)
            elif name == "move":
                self.on_move(x, y)
            elif name == "up":
                self.on_up(x, y)

    # ---- tray ----
    def _build_tray(self):
        icon = self._make_icon()
        self.tray = QtWidgets.QSystemTrayIcon(icon)
        self.tray.setToolTip("QR Shot - right-drag to capture")
        menu = QtWidgets.QMenu()
        self.act_toggle = menu.addAction("Enabled (right-drag)")
        self.act_toggle.setCheckable(True)
        self.act_toggle.setChecked(True)
        self.act_toggle.triggered.connect(self._set_enabled)
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

    def _set_enabled(self, on):
        self._enabled = on
        if not on and self.overlay:
            self.overlay.close_overlay()

    # ---- hook -> overlay ----
    def _to_logical(self, x, y):
        dpr = _dpr_at(x, y) or 1.0
        vr = self.overlay.vr if self.overlay else None
        lx, ly = x / dpr, y / dpr
        if vr:
            lx -= vr.left()
            ly -= vr.top()
        return int(lx), int(ly)

    def on_down(self, x, y):
        if self.paused():
            return
        self.show_overlay()
        lx, ly = self._to_logical(x, y)
        self.overlay.begin_drag(lx, ly)

    def on_move(self, x, y):
        if self.overlay and self.overlay.isVisible() and self._dragging_active():
            lx, ly = self._to_logical(x, y)
            self.overlay.update_drag(lx, ly)

    def on_up(self, x, y):
        if self.overlay and self.overlay.isVisible() and self._dragging_active():
            lx, ly = self._to_logical(x, y)
            self.overlay.end_drag(lx, ly)

    def _dragging_active(self):
        return self.overlay is not None and getattr(self.overlay, "_dragging_region", False)

    def paused(self):
        return not self._enabled or (self.overlay is not None and self.overlay.isVisible())

    def show_overlay(self):
        if self.overlay:
            self.overlay.close()
        self.overlay = Overlay(self.handle_decode)
        self.overlay.finished.connect(self._on_overlay_done)
        self.overlay.show()
        self.overlay.raise_()
        self.overlay.activateWindow()

    def _on_overlay_done(self):
        self.overlay = None

    # ---- decode ----
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
            self._watchdog.stop()
            self.hook.stop()
            self.hook.join(timeout=1.0)
        except Exception:
            pass
        self.q.quit()


def _single_instance():
    import ctypes
    k = ctypes.windll.kernel32
    k.CreateMutexW(None, False, "Global\\QRShotSingleInstance_v1")
    return k.GetLastError() != 183  # 183 = ERROR_ALREADY_EXISTS


def main():
    if not _single_instance():
        sys.exit(0)
    mouse_hook.set_dpi_aware()
    qapp = QtWidgets.QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    app = App(qapp)
    sys.exit(qapp.exec())


if __name__ == "__main__":
    main()
