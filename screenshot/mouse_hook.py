"""mouse_hook.py - global low-level mouse hook (Win32, ctypes).

This is the only mechanism that reads the right button on machines where
GetAsyncKeyState/Raw Input do not expose it. It detects a right-DRAG and
swallows those events (so the desktop context menu does not open); a plain
right click is never swallowed.

Safety: the hook procedure only enqueues an event and returns - it never
touches Qt, never grabs the screen, never blocks. All ctypes signatures are set
explicitly (a missing argtypes made the 64-bit lParam overflow and raise on
every event, which is what previously wedged input).
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import queue
import threading
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.windll.kernel32

_DBG = None

LRESULT = ctypes.c_ssize_t
WH_MOUSE_LL = 14
WM_MOUSEMOVE, WM_RBUTTONDOWN, WM_RBUTTONUP, WM_RBUTTONDBLCLK, WM_QUIT = \
    0x0200, 0x0204, 0x0205, 0x0206, 0x0012

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
    def __init__(self, threshold: int = 6):
        super().__init__(daemon=True)
        self.events: "queue.Queue[tuple[str, int, int, float]]" = queue.Queue(maxsize=8192)
        self.subs: list = []
        self.threshold = threshold
        self._dragging = False
        self._pressed = False
        self._down_pos = (0, 0)
        self._last = 0.0
        self._proc = HOOKPROC(self._handler)
        self._hook = None
        self._tid = 0
        self._stop = threading.Event()

    def add_subscriber(self, fn):
        """Register a callback(name, x, y) invoked by the message pump (running
        in this thread). Eliminates any polling delay."""
        self.subs.append(fn)

    def _handler(self, n_code, w_param, l_param):
        if n_code < 0:
            return user32.CallNextHookEx(self._hook, n_code, w_param, l_param)
        swallow = False
        try:
            info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            x, y = info.pt.x, info.pt.y
            now = time.monotonic()
            if w_param in (WM_RBUTTONDOWN, WM_RBUTTONDBLCLK):
                self._pressed = True
                self._dragging = False
                self._down_pos = (x, y)
                self._last = now
            elif w_param == WM_MOUSEMOVE:
                # NEVER swallow mouse moves: swallowing WM_MOUSEMOVE tells
                # Windows not to move the cursor, which freezes the pointer.
                if self._pressed:
                    if not self._dragging and (abs(x - self._down_pos[0]) > self.threshold
                                               or abs(y - self._down_pos[1]) > self.threshold):
                        self._dragging = True
                        self._push("down", *self._down_pos)
                    if self._dragging:
                        self._push("move", x, y)
                # watchdog: if a drag seems stuck with no button event for a
                # while, drop it so we never get wedged in a swallow state.
                if self._dragging and now - self._last > 1.5:
                    self._dragging = False
                    self._pressed = False
                    self._push("up", x, y)
            elif w_param == WM_RBUTTONUP:
                self._last = now
                self._pressed = False
                if self._dragging:
                    self._dragging = False
                    self._push("up", x, y)
                    swallow = True   # suppress the desktop context menu
        except Exception:
            pass
        # Only ever swallow right-button up (to hide the menu). Moves pass.
        return 1 if swallow else user32.CallNextHookEx(self._hook, n_code, w_param, l_param)

    def _push(self, name, x, y):
        try:
            self.events.put_nowait((name, x, y, time.monotonic()))
        except queue.Full:
            pass
        for fn in self.subs:
            try:
                fn(name, x, y)
            except Exception:
                pass
        if _DBG:
            try:
                _DBG.write(f"{time.time():.3f} {name} @({x},{y})\n")
                _DBG.flush()
            except Exception:
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
