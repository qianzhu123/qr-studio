"""hotkey.py - Global hotkey via Win32 RegisterHotKey (NO mouse hook).

RegisterHotKey does not install a low-level hook, so it can never stall or
freeze mouse/keyboard input. The hotkey is registered on a dedicated thread
with its own message loop; when it fires, WM_HOTKEY is received there and an
event is pushed to a queue that the Qt main thread polls.

This replaces the earlier low-level mouse-hook trigger, which proved unsafe on
some setups (a mis-behaving LL hook can wedge system input).
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import queue
import threading

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.windll.kernel32

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

user32.RegisterHotKey.argtypes = [w.HWND, ctypes.c_int, w.UINT, w.UINT]
user32.RegisterHotKey.restype = w.BOOL
user32.UnregisterHotKey.argtypes = [w.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = w.BOOL


def parse(combo: str):
    """'Ctrl+Alt+Q' -> (modifiers, vk)."""
    mods = MOD_NOREPEAT
    vk = None
    for part in combo.replace(" ", "").split("+"):
        p = part.lower()
        if p in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif p == "alt":
            mods |= MOD_ALT
        elif p == "shift":
            mods |= MOD_SHIFT
        elif p in ("win", "meta"):
            mods |= MOD_WIN
        elif len(p) == 1:
            vk = ord(p.upper())
        elif p.startswith("f") and p[1:].isdigit():
            vk = 0x6F + int(p[1:])  # F1 = 0x70
    if vk is None:
        raise ValueError(f"no key in hotkey: {combo}")
    return mods, vk


class Hotkey(threading.Thread):
    """Registers one global hotkey and reports fires via self.fired (a Queue)."""

    def __init__(self, combo: str = "Ctrl+Alt+Q"):
        super().__init__(daemon=True)
        self.combo = combo
        self.fired: "queue.Queue[bool]" = queue.Queue(maxsize=64)
        self._tid = 0
        self._stop = threading.Event()
        self.ok = False

    def run(self):
        self._tid = kernel32.GetCurrentThreadId()
        try:
            mods, vk = parse(self.combo)
        except Exception:
            return
        if not user32.RegisterHotKey(None, 1, mods, vk):
            return  # hotkey taken; thread exits, ok stays False
        self.ok = True
        msg = w.MSG()
        while not self._stop.is_set():
            r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r == 0 or r == -1:
                break
            if msg.message == WM_HOTKEY:
                try:
                    self.fired.put_nowait(True)
                except queue.Full:
                    pass
        user32.UnregisterHotKey(None, 1)

    def stop(self):
        self._stop.set()
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
