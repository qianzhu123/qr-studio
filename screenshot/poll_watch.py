"""poll_watch.py - Right-button DRAG detection by POLLING, with NO hook.

This is the safe way to get a right-drag gesture on Windows: instead of a
low-level mouse hook (which can stall or freeze system input if it misbehaves),
we periodically read the physical button state with GetAsyncKeyState and the
cursor position with GetCursorPos. Polling never intercepts or blocks any
event, so it can never wedge the mouse, and a plain right click is left entirely
alone (the normal context menu still appears).

When the right button is held and the cursor moves past THRESHOLD px, a drag is
reported: "down" (once), then "move" while held, then "up" on release.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w

import os
from PySide6 import QtCore

_LOG = open(os.path.join(os.path.dirname(__file__), 'watcher.log'), 'w', encoding='utf-8') \
    if os.environ.get("QR_SHOT_DEBUG") else None

user32 = ctypes.windll.user32
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetCursorPos.argtypes = [ctypes.POINTER(w.POINT)]
user32.GetCursorPos.restype = w.BOOL

VK_RBUTTON = 0x02


def _down(vk: int) -> bool:
    return user32.GetAsyncKeyState(vk) & 0x8000 != 0


def _pos():
    p = w.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


class RightDragWatcher(QtCore.QObject):
    """Polls for a right-button drag. Emits logical coords for the overlay."""

    down = QtCore.Signal(int, int)
    move = QtCore.Signal(int, int)
    up = QtCore.Signal(int, int)

    def __init__(self, threshold: int = 6, interval_ms: int = 8):
        super().__init__()
        self.threshold = threshold
        self._prev_down = False
        self._armed = False       # right button currently pressed
        self._dragging = False
        self._start = (0, 0)
        self._enabled = True
        self._timer = QtCore.QTimer()
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_enabled(self, on: bool):
        self._enabled = on
        if not on:
            self._armed = self._dragging = False

    def _force_release(self, x, y):
        was_dragging = self._dragging
        self._dragging = False
        self._armed = False
        self._start = (0, 0)
        if was_dragging:
            self.up.emit(x, y)

    def _tick(self):
        if not self._enabled:
            return
        down_now = _down(VK_RBUTTON)
        x, y = _pos()
        if _LOG:
            _LOG.write("tick down=%s armed=%s drag=%s pos=(%d,%d)\n"
                       % (down_now, self._armed, self._dragging, x, y))
            _LOG.flush()

        # Fast drags can press and release between two polls, so the button is
        # seen up while our internal state still says a drag is active. Detect
        # that single "up" tick and finalize instead of losing the selection.
        if self._prev_down and not down_now and self._armed:
            self._force_release(x, y)
            self._prev_down = down_now
            return

        if down_now and not self._armed:
            self._armed = True
            self._dragging = False
            self._start = (x, y)
        elif down_now and self._armed and not self._dragging:
            if abs(x - self._start[0]) > self.threshold or abs(y - self._start[1]) > self.threshold:
                self._dragging = True
                self.down.emit(*self._start)
                self.move.emit(x, y)
        elif down_now and self._dragging:
            self.move.emit(x, y)

        self._prev_down = down_now
