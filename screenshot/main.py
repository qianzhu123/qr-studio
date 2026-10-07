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
import mouse_hook  # noqa: E402
from poll_watch import RightDragWatcher  # noqa: E402

try:
    from qr_decode import decode_image, trace_redirects
except Exception:
    decode_image = trace_redirects = None

OVERLAY_TIMEOUT_MS = 45000      # self-close a stuck overlay
CAPTURE_HOTKEY = os.environ.get("QR_SHOT_HOTKEY", "Ctrl+Alt+A")
QUIT_HOTKEY = os.environ.get("QR_SHOT_QUIT_HOTKEY", "Ctrl+Alt+Q")


# --------------------------------------------------------------------------
# Minimal global hotkeys (RegisterHotKey only - no hook, cannot stall input)
# --------------------------------------------------------------------------

import ctypes.wintypes as _w  # noqa: E402
import threading  # noqa: E402
import queue as _queue  # noqa: E402

_MOD_ALT, _MOD_CONTROL, _MOD_SHIFT, _MOD_WIN, _MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
_WM_HOTKEY, _WM_QUIT = 0x0312, 0x0012


def _parse_hotkey(combo):
    mods, vk = _MOD_NOREPEAT, None
    for part in combo.replace(" ", "").split("+"):
        p = part.lower()
        if p in ("ctrl", "control"):
            mods |= _MOD_CONTROL
        elif p == "alt":
            mods |= _MOD_ALT
        elif p == "shift":
            mods |= _MOD_SHIFT
        elif p in ("win", "meta"):
            mods |= _MOD_WIN
        elif len(p) == 1:
            vk = ord(p.upper())
        elif p.startswith("f") and p[1:].isdigit():
            vk = 0x6F + int(p[1:])
    return mods, vk


class Hotkeys(threading.Thread):
    """Registers the quit hotkey via RegisterHotKey. No hook."""

    def __init__(self, capture=CAPTURE_HOTKEY, quit_=QUIT_HOTKEY):
        super().__init__(daemon=True)
        self.capture = capture
        self.quit = quit_
        self.fired = _queue.Queue(maxsize=16)   # "quit"
        self._tid = 0
        self.capture_ok = False

    def run(self):
        u = ctypes.windll.user32
        self._tid = ctypes.windll.kernel32.GetCurrentThreadId()
        mq, vq = _parse_hotkey(self.quit)
        if vq is not None:
            u.RegisterHotKey(None, 2, mq, vq)
        msg = _w.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == _WM_HOTKEY:
                try:
                    self.fired.put_nowait("quit")
                except Exception:
                    pass
        u.UnregisterHotKey(None, 2)

    def stop(self):
        if self._tid:
            ctypes.windll.user32.PostThreadMessageW(self._tid, _WM_QUIT, 0, 0)


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
        # Trigger = RIGHT-BUTTON DRAG.
        #  - primary: low-level hook (immediate, works on machines where polling
        #    cannot read the right button); only right-button-UP is swallowed
        #    (to hide the context menu), moves are never swallowed.
        #  - fallback: polling, in case the hook is blocked by another process.
        self.hook = mouse_hook.MouseHook(threshold=6)
        self.hook.start()
        self._hook_timer = QtCore.QTimer()
        self._hook_timer.setInterval(5)
        self._hook_timer.timeout.connect(self._pump_hook)
        self._hook_timer.start()
        self.watcher = RightDragWatcher(threshold=6)
        self.watcher.down.connect(self.on_down)
        self.watcher.move.connect(self.on_move)
        self.watcher.up.connect(self.on_up)
        self._overlay_timer = QtCore.QTimer()
        self._overlay_timer.setSingleShot(True)
        self._overlay_timer.timeout.connect(self._overlay_timeout)
        self.hotkeys = Hotkeys()
        self.hotkeys.start()
        self._hk_timer = QtCore.QTimer()
        self._hk_timer.setInterval(150)
        self._hk_timer.timeout.connect(self._poll_quit_hotkey)
        self._hk_timer.start()

    def _poll_quit_hotkey(self):
        try:
            what = self.hotkeys.fired.get_nowait()
        except Exception:
            return
        if what == "quit":
            self.quit()

    def _pump_hook(self):
        while True:
            try:
                name, x, y, ts = self.hook.events.get_nowait()
            except Exception:
                return
            try:
                if name == "down":
                    self.on_down(x, y)
                elif name == "move":
                    self.on_move(x, y)
                elif name == "up":
                    self.on_up(x, y)
            except Exception as e:
                print("hook event error:", e, flush=True)

    def _overlay_timeout(self):
        if self.overlay and self.overlay.isVisible():
            self.overlay.close_overlay()

    # ---- right-drag -> overlay ----
    def _logical(self, x, y):
        """Physical cursor (x, y) -> overlay-local LOGICAL coordinates.

        Must test containment against each screen's PHYSICAL rect
        (geometry * dpr), because GetCursorPos returns device pixels while
        Qt geometry is in logical pixels. Mixing the two made the lower part
        of a scaled screen fall outside every screen and break selection.
        """
        vr = self.overlay.vr if self.overlay else None
        for s in QtGui.QGuiApplication.screens():
            g = s.geometry()
            dpr = s.devicePixelRatio() or 1.0
            phys = QtCore.QRect(int(g.x() * dpr), int(g.y() * dpr),
                                int(g.width() * dpr), int(g.height() * dpr))
            if phys.contains(x, y):
                lx, ly = x / dpr, y / dpr
                if vr:
                    lx -= vr.left()
                    ly -= vr.top()
                return int(lx), int(ly)
        dpr = QtGui.QGuiApplication.primaryScreen().devicePixelRatio() or 1.0
        lx, ly = x / dpr, y / dpr
        if vr:
            lx -= vr.left()
            ly -= vr.top()
        return int(lx), int(ly)

    def on_down(self, x, y):
        # Skip a drag that starts on top of a pinned image so the pin can
        # receive the click (right-click reopens the toolbar, double-click
        # closes). This is not a hook, just a geometric check.
        if self._point_in_pin(x, y):
            return
        if self.overlay is not None and self.overlay.isVisible():
            return
        self.capture()
        lx, ly = self._logical(x, y)
        self.overlay.begin_drag(lx, ly)
        self._overlay_timer.start(OVERLAY_TIMEOUT_MS)

    def _point_in_pin(self, x, y):
        import overlay as _ov
        for w in list(_ov._PINS):
            if w.isVisible() and w.frameGeometry().contains(x, y):
                return True
        return False

    def on_move(self, x, y):
        if self.overlay and self.overlay.isVisible():
            lx, ly = self._logical(x, y)
            self.overlay.update_drag(lx, ly)

    def on_up(self, x, y):
        if self.overlay and self.overlay.isVisible():
            lx, ly = self._logical(x, y)
            self.overlay.hook_release(lx, ly)
            # The hook swallows the drag, but a modern Win11 desktop may still
            # have queued its menu; close it if it appears (target the popup
            # window only, never the overlay).
            self._schedule_menu_dismiss()

    def _schedule_menu_dismiss(self):
        for delay in (60, 160, 320):
            QtCore.QTimer.singleShot(delay, self._dismiss_menu_if_any)

    def _dismiss_menu_if_any(self):
        u = ctypes.windll.user32
        hwnd = u.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(hwnd, buf, 64)
        if buf.value == "#32768":        # standard Win32 popup menu class
            # WM_KEYDOWN / WM_KEYUP of VK_ESCAPE closes the menu
            u.PostMessageW(hwnd, 0x0100, 0x1B, 0)
            u.PostMessageW(hwnd, 0x0101, 0x1B, 0)

    # ---- tray ----
    def _build_tray(self):
        self.tray = QtWidgets.QSystemTrayIcon(self._make_icon())
        self.tray.setToolTip("QR Shot - right-drag to capture")
        menu = QtWidgets.QMenu()
        menu.addAction("Decode from clipboard", self.decode_clipboard)
        menu.addAction("Settings...", self._open_settings)
        menu.addSeparator()
        menu.addAction(f"Quit  ({QUIT_HOTKEY})", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.show()

    def _open_settings(self):
        from settings_app import SettingsDialog
        SettingsDialog().exec()

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
        # Grab the desktop ONCE, before the overlay window exists, so the frozen
        # image never contains the overlay itself.
        import overlay as _ov
        from overlay import Overlay as _Overlay
        desk = _ov.grab_desktop_pixmap()
        self.overlay = _Overlay(self.handle_decode, desk=desk)
        self.overlay.reopen_handler = self._reopen_overlay
        self.overlay.finished.connect(self._on_overlay_done)
        self.overlay.show()

    def _reopen_overlay(self, x, y):
        """A pinned image was right-clicked: open a fresh overlay to select
        again, starting a new drag at that point."""
        self.capture()
        lx, ly = self._logical(x, y)
        self.overlay.begin_drag(lx, ly)
        self._overlay_timer.start(OVERLAY_TIMEOUT_MS)

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
            self._hk_timer.stop()
            self._hook_timer.stop()
            self.hotkeys.stop()
            self.hook.stop()
            self.hook.join(timeout=1.0)
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
