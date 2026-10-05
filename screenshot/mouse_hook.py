"""mouse_hook.py - Global low-level mouse hook (Win32) via ctypes.

Purpose: detect a RIGHT-BUTTON DRAG (press, move past a threshold while held,
release). A plain right click is passed through untouched, so the normal
context menu still appears. This is run on the process main thread which pumps
messages with GetMessageW.

It can either observe-only or swallow the drag events (so the drag does not
reach other apps). Callback receives events: "down", "move", "up", "cancel".
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WH_MOUSE_LL = 14
WM_MOUSEMOVE = 0x0200
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEWHEEL = 0x020A
WM_RBUTTONDBLCLK = 0x0206
WM_MOUSEHWHEEL = 0x020E
WM_QUIT = 0x0012

LRESULT = ctypes.c_ssize_t


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", w.POINT), ("mouseData", w.DWORD), ("flags", w.DWORD),
                ("time", w.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, w.WPARAM, w.LPARAM)


def set_dpi_aware():
    """Make coordinates physical pixels across monitors (call before any UI)."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE_V2
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def cursor_pos():
    p = w.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


class MouseHook:
    """Low-level mouse hook dispatching right-drag events to a callback.

    callback(name, x, y) -> bool
        name in {"down", "move", "up", "cancel"}
        return True to swallow the event (block it from other apps), else False.
    Movement events are only emitted while a right-drag is in progress; once
    the drag starts, subsequent moves are swallowed so other apps do not react.
    """

    def __init__(self, callback, threshold: int = 6):
        self.cb = callback
        self.threshold = threshold
        self._dragging = False
        self._down_pos = (0, 0)
        self._proc = HOOKPROC(self._handler)
        self._hook = None
        self._msg = w.MSG()

    def _handler(self, n_code, w_param, l_param):
        if n_code == 0 and w_param in (WM_RBUTTONDOWN, WM_MOUSEMOVE, WM_RBUTTONUP,
                                       WM_RBUTTONDBLCLK):
            info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            x, y = info.pt.x, info.pt.y
            if w_param == WM_RBUTTONDOWN or w_param == WM_RBUTTONDBLCLK:
                self._dragging = False
                self._down_pos = (x, y)
                # do NOT swallow: a plain click must still open the menu
            elif w_param == WM_MOUSEMOVE and self._down_pos:
                dx = abs(x - self._down_pos[0])
                dy = abs(y - self._down_pos[1])
                if not self._dragging and (dx > self.threshold or dy > self.threshold):
                    self._dragging = True
                    if self.cb("down", *self._down_pos):
                        return 1
                if self._dragging:
                    if self.cb("move", x, y):
                        return 1
            elif w_param == WM_RBUTTONUP:
                if self._dragging:
                    self._dragging = False
                    self._down_pos = (0, 0)
                    if self.cb("up", x, y):
                        return 1
                else:
                    self._down_pos = (0, 0)
        return user32.CallNextHookEx(self._hook, n_code, w_param, l_param)

    def install(self):
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, None, 0)
        if not self._hook:
            raise OSError("SetWindowsHookExW failed (error %d)" % kernel32.GetLastError())

    def uninstall(self):
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def run(self):
        """Message pump. Blocks; call stop() from another thread to exit."""
        if not self._hook:
            self.install()
        while user32.GetMessageW(ctypes.byref(self._msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(self._msg))
            user32.DispatchMessageW(ctypes.byref(self._msg))

    def stop(self):
        user32.PostThreadMessageW(kernel32.GetCurrentThreadId(), WM_QUIT, 0, 0)
