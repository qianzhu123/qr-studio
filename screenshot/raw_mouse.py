"""raw_mouse.py - right-button drag detection via Win32 Raw Input.

Why this instead of polling or a hook:
  - Polling (GetAsyncKeyState) can miss the physical right button when a mouse
    driver/utility remaps it (observed on this machine).
  - A low-level hook CAN see it but may wedge system input - unsafe.
  - Raw Input reads the device's button events directly, works in the
    background (RIDEV_INPUTSINK), and NEVER intercepts or blocks input, so it
    cannot freeze the mouse or keyboard.

Runs a message-only window on its own thread; button/move events are pushed to
a queue that the Qt main thread polls.
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

WM_INPUT = 0x00FF
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_QUIT = 0x0012

RID_INPUT = 0x10000003
RIDEV_INPUTSINK = 0x00000100
HWND_MESSAGE = -3

RIM_TYPEMOUSE = 0

RI_MOUSE_LEFT_BUTTON_DOWN = 0x0001
RI_MOUSE_LEFT_BUTTON_UP = 0x0002
RI_MOUSE_RIGHT_BUTTON_DOWN = 0x0004
RI_MOUSE_RIGHT_BUTTON_UP = 0x0008
RI_MOUSE_MOVE_ABSOLUTE = 0x0001  # in usFlags
MOUSE_MOVE_ABSOLUTE = 0x01


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", w.USHORT), ("usUsage", w.USHORT),
                ("dwFlags", w.DWORD), ("hwndTarget", w.HWND)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", w.DWORD), ("dwSize", w.DWORD),
                ("hDevice", w.HANDLE), ("wParam", w.WPARAM)]


class RAWMOUSE(ctypes.Structure):
    _fields_ = [("usFlags", w.USHORT), ("usButtonFlags", w.USHORT),
                ("usButtonData", w.USHORT), ("ulRawButtons", w.ULONG),
                ("lLastX", ctypes.c_long), ("lLastY", ctypes.c_long),
                ("ulExtraInformation", w.ULONG)]


class RAWINPUT(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("mouse", RAWMOUSE)]


WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", w.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", w.HINSTANCE), ("hIcon", w.HICON),
                ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH),
                ("lpszMenuName", w.LPCWSTR), ("lpszClassName", w.LPCWSTR)]


def _cursor():
    p = w.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


class RawMouse(threading.Thread):
    """Reports right-drag events ("down"/"move"/"up") via self.events queue."""

    def __init__(self, threshold: int = 6):
        super().__init__(daemon=True)
        self.events: "queue.Queue[tuple[str, int, int, float]]" = queue.Queue(maxsize=8192)
        self.threshold = threshold
        self._held = False
        self._dragging = False
        self._start = (0, 0)
        self._tid = 0
        self._stop = threading.Event()
        self.ready = False
        self._wndproc = WNDPROC(self._on_message)
        self._hwnd = None

    # ---- window proc (runs on the raw-mouse thread) ----
    def _on_message(self, hwnd, msg, wparam, lparam):
        if msg == WM_INPUT:
            try:
                self._handle_input(lparam)
            except Exception:
                pass
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
        if msg == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _handle_input(self, lparam):
        size = w.UINT(0)
        user32.GetRawInputData.argtypes = [w.HANDLE, w.UINT, ctypes.c_void_p,
                                           ctypes.POINTER(w.UINT), w.UINT]
        user32.GetRawInputData.restype = w.UINT
        hdr_size = ctypes.sizeof(RAWINPUTHEADER)
        if user32.GetRawInputData(lparam, RID_INPUT, None, ctypes.byref(size), hdr_size) != 0:
            return
        buf = ctypes.create_string_buffer(size.value)
        if user32.GetRawInputData(lparam, RID_INPUT, buf, ctypes.byref(size), hdr_size) != size.value:
            return
        raw = ctypes.cast(buf, ctypes.POINTER(RAWINPUT)).contents
        if raw.header.dwType != RIM_TYPEMOUSE:
            return
        flags = raw.mouse.usButtonFlags
        x, y = _cursor()
        now = time.monotonic()

        if flags & RI_MOUSE_RIGHT_BUTTON_DOWN:
            self._held = True
            self._dragging = False
            self._start = (x, y)
        if flags & RI_MOUSE_RIGHT_BUTTON_UP:
            if self._dragging:
                self._dragging = False
                self._push("up", x, y, now)
            self._held = False
        moved = (raw.mouse.lLastX or raw.mouse.lLastY)
        if self._held and moved:
            if not self._dragging:
                if abs(x - self._start[0]) > self.threshold or abs(y - self._start[1]) > self.threshold:
                    self._dragging = True
                    self._push("down", *self._start, now)
            if self._dragging:
                self._push("move", x, y, now)

    def _push(self, name, x, y, ts):
        try:
            self.events.put_nowait((name, x, y, ts))
        except queue.Full:
            pass

    # ---- thread ----
    def run(self):
        self._tid = kernel32.GetCurrentThreadId()
        hinst = kernel32.GetModuleHandleW(None)
        # explicit argtypes: without them, pointer params (window handles,
        # class name) are mis-passed on 64-bit and CreateWindowExW fails.
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        user32.RegisterClassW.restype = w.ATOM
        user32.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE,
                                           ctypes.c_void_p]
        user32.CreateWindowExW.restype = w.HWND
        user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE),
                                                   w.UINT, w.UINT]
        user32.RegisterRawInputDevices.restype = w.BOOL
        user32.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        user32.DefWindowProcW.restype = LRESULT

        cls = WNDCLASSW()
        cls.lpfnWndProc = self._wndproc
        cls.hInstance = hinst
        cls.lpszClassName = "QRShotRawMouse"
        user32.RegisterClassW(ctypes.byref(cls))   # ignore if already exists
        self._hwnd = user32.CreateWindowExW(0, "QRShotRawMouse", "QRShotRawMouse",
                                            0, 0, 0, 0, 0, None, None, hinst, None)
        if not self._hwnd:
            return
        rid = RAWINPUTDEVICE(0x01, 0x02, RIDEV_INPUTSINK, self._hwnd)
        ok = user32.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(RAWINPUTDEVICE))
        self.ready = bool(ok)
        msg = w.MSG()
        while not self._stop.is_set():
            r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r == 0 or r == -1:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def stop(self):
        self._stop.set()
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
