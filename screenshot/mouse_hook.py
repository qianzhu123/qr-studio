"""mouse_hook.py - Global low-level mouse hook (Win32) via ctypes.

SAFETY CONTRACT (learned the hard way):
A low-level mouse hook that does not return quickly will stall mouse input for
the WHOLE SYSTEM. Therefore the hook procedure here does the absolute minimum:
it appends a tuple to a thread-safe queue and returns. It never touches Qt,
never emits signals, never grabs the screen, never blocks.

Right-button DRAG detection: press, move past a threshold while held, release.
A plain right click is never reported as a drag and is never swallowed.

`swallow=False` (default) makes the hook fully observe-only: it never blocks any
mouse event. Set swallow=True only if you really need to hide the drag from
other apps; even then only drag-time events are swallowed.
"""
from __future__ import annotations

import ctypes
import queue
import threading
import time
import ctypes.wintypes as w

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.windll.kernel32

LRESULT = ctypes.c_ssize_t

# Correct CFUNCTYPE signatures for 64-bit. Without explicit argtypes, ctypes
# assumes 32-bit int for the lParam pointer, which overflows and makes
# CallNextHookEx raise on every event, breaking the hook chain and flooding
# stderr with "Exception ignored" messages.
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, w.WPARAM, w.LPARAM)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, w.HINSTANCE, w.DWORD]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, w.WPARAM, w.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.UnhookWindowsHookEx.restype = w.BOOL

WH_MOUSE_LL = 14
WM_MOUSEMOVE = 0x0200
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_RBUTTONDBLCLK = 0x0206
WM_QUIT = 0x0012


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
    """Runs a message pump on its own thread and reports right-drag events.

    Events are pushed to self.events (a queue.Queue) as (name, x, y) with name
    in {"down", "move", "up"}. The consumer (Qt main thread) polls this queue.
    """

    def __init__(self, swallow: bool = False, threshold: int = 6, poll_max_age: float = 3.0):
        super().__init__(daemon=True)
        self.events: "queue.Queue[tuple[str, int, int]]" = queue.Queue(maxsize=4096)
        self.swallow = swallow
        self.threshold = threshold
        self.poll_max_age = poll_max_age
        self._dragging = False
        self._down_pos = (0, 0)
        self._proc = HOOKPROC(self._handler)  # keep a reference alive
        self._hook = None
        self._tid = 0
        self._stop = threading.Event()

    # ---- hook procedure: MUST be trivial and fast ----
    def _handler(self, n_code, w_param, l_param):
        try:
            # HC_ACTION (0) is the only case that carries input; call through
            # immediately for any negative code.
            if n_code < 0:
                return user32.CallNextHookEx(self._hook, n_code, w_param, l_param)
            if n_code == 0 and w_param in (WM_RBUTTONDOWN, WM_RBUTTONUP, WM_MOUSEMOVE,
                                           WM_RBUTTONDBLCLK):
                info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                x, y = info.pt.x, info.pt.y
                if w_param in (WM_RBUTTONDOWN, WM_RBUTTONDBLCLK):
                    self._dragging = False
                    self._down_pos = (x, y)
                elif w_param == WM_MOUSEMOVE and self._down_pos:
                    if not self._dragging:
                        if (abs(x - self._down_pos[0]) > self.threshold
                                or abs(y - self._down_pos[1]) > self.threshold):
                            self._dragging = True
                            self._put("down", *self._down_pos)
                    if self._dragging:
                        self._put("move", x, y)
                elif w_param == WM_RBUTTONUP:
                    if self._dragging:
                        self._dragging = False
                        self._down_pos = (0, 0)
                        self._put("up", x, y)
                    else:
                        self._down_pos = (0, 0)
            # swallow only drag-time events, and only if explicitly requested
            if self.swallow and self._dragging:
                return 1
        except Exception:
            pass  # never let an exception escape into the hook
        return user32.CallNextHookEx(self._hook, n_code, w_param, l_param)

    def _put(self, name, x, y):
        try:
            self.events.put_nowait((name, x, y, time.monotonic()))
        except queue.Full:
            pass  # drop rather than block; input must never stall

    # ---- thread ----
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
