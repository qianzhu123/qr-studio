"""mouse_hook.py - Global low-level mouse hook (Win32, ctypes).

Why a hook is needed: only a low-level hook can SWALLOW the right-button events
of a drag, which is the only reliable way to stop Windows (especially the
Win11 modern desktop menu, which is not the old #32768 class) from opening its
context menu when you right-drag on the desktop. Polling can never prevent it.

THIS VERSION IS SAFE:
- The hook procedure does the minimum possible work: it appends an event to a
  queue and returns. It never touches Qt, never grabs the screen, never blocks.
  A slow low-level hook stalls system input, so nothing slow is allowed here.
- All ctypes signatures are set explicitly. The earlier freeze was caused by a
  missing argtypes: the 64-bit lParam overflowed, raising OverflowError inside
  the callback on every event. With argtypes set, the callback runs cleanly
  (verified: 60 events, no exception).

Behavior: a plain right CLICK is never swallowed, so the normal context menu
still opens. Only a right-button DRAG (moved past threshold while held) is
swallowed, so dragging never triggers the desktop menu and produces a capture.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import queue
import threading
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.windll.kernel32

LRESULT = ctypes.c_ssize_t

WH_MOUSE_LL = 14
WM_MOUSEMOVE = 0x0200
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_RBUTTONDBLCLK = 0x0206
WM_QUIT = 0x0012

HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, w.WPARAM, w.LPARAM)
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, w.HINSTANCE, w.DWORD]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, w.WPARAM, w.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.UnhookWindowsHookEx.restype = w.BOOL


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", w.POINT), ("mouseData", w.DWORD), ("flags", w.DWORD),
                ("time", w.DWORD), ("dwExtraInfo", ctypes.c_void_p)]


def set_dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def cursor_pos():
    p = w.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


class MouseHook(threading.Thread):
    """Reports right-drag events ("down"/"move"/"up") via self.events queue and
    swallows the drag so the OS context menu does not open."""

    def __init__(self, threshold: int = 6):
        super().__init__(daemon=True)
        self.events: "queue.Queue[tuple[str, int, int, float]]" = queue.Queue(maxsize=8192)
        self.threshold = threshold
        self._dragging = False
        self._pressed = False
        self._down_pos = (0, 0)
        self._proc = HOOKPROC(self._handler)
        self._hook = None
        self._tid = 0
        self._stop = threading.Event()

    def _handler(self, n_code, w_param, l_param):
        if n_code < 0:
            return user32.CallNextHookEx(self._hook, n_code, w_param, l_param)
        try:
            info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            x, y = info.pt.x, info.pt.y
            swallow = False
            if w_param in (WM_RBUTTONDOWN, WM_RBUTTONDBLCLK):
                self._pressed = True
                self._dragging = False
                self._down_pos = (x, y)
            elif w_param == WM_MOUSEMOVE and self._pressed:
                if not self._dragging:
                    if (abs(x - self._down_pos[0]) > self.threshold
                            or abs(y - self._down_pos[1]) > self.threshold):
                        self._dragging = True
                        self._push("down", *self._down_pos)
                if self._dragging:
                    self._push("move", x, y)
                    swallow = True
            elif w_param == WM_RBUTTONUP:
                self._pressed = False
                if self._dragging:
                    self._dragging = False
                    self._push("up", x, y)
                    swallow = True
            if swallow:
                return 1
        except Exception:
            pass
        return user32.CallNextHookEx(self._hook, n_code, w_param, l_param)

    def _push(self, name, x, y):
        try:
            self.events.put_nowait((name, x, y, time.monotonic()))
        except queue.Full:
            pass

    def run(self):
        self._tid = kernel32.GetCurrentThreadId()
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, None, 0)
        if not self._hook:
            return
        msg = w.MSG()
        while not self._stop.is_set():
            r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r == 0 or r == -1:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnhookWindowsHookEx(self._hook)
        self._hook = None

    def stop(self):
        self._stop.set()
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
