"""input_lock.py - how a low-level mouse hook can make the mouse stop
responding, with a guaranteed, input-independent way out.

WHAT THIS SHOWS
---------------
Windows delivers every mouse event to low-level hooks (WH_MOUSE_LL) *before*
any application sees it. If a hook returns 1 instead of calling
CallNextHookEx, the event is "swallowed": the system drops it. Swallow every
event and the cursor stops moving and clicks stop landing - which is exactly
what a heavy-handed hook does by accident. This file does it on purpose, to
demonstrate the mechanism, and only inside a strict time-box.

WHY THIS IS SAFE TO RUN
-----------------------
A lock that depends on the locked input is a trap (you cannot click "unlock").
So this script makes the lock release itself without any user input:

  * a wall-clock timer holds the lock for at most `--seconds` (default 3);
  * after that it calls UnhookWindowsHookEx and exits, no matter what;
  * press Ctrl+C in the console at any time to abort early (the console still
    receives keyboard input; only the mouse is affected);
  * if the process is killed, the OS removes the hook automatically, because a
    WH_MOUSE_LL hook lives and dies with the thread that installed it.

There is also set_input_back(True) / BlockInput for reference, but the default
path never touches the keyboard.

WHY A HOOK ALONE ONLY *SLOWS* INPUT
-----------------------------------
Swallowing events in a WH_MOUSE_LL hook is not fully reliable: Windows enforces
a LowLevelHooksTimeout (HKCU\Control Panel\Desktop\LowLevelHooksTimeout, ~300ms
by default) and will pass an event through - or drop your hook entirely - if the
callback is late (Python GIL/GC jitter is enough). Some drivers also move the
cursor below the hook. The result is stutter, not a hard lock.

For a HARD freeze of movement there is a better mechanism: ClipCursor confines
the pointer to a rectangle. Pinning it to a 1x1 rect makes the cursor physically
unable to move. That is what --pin uses; the hook is kept only to swallow clicks.

USAGE (you decide when to run it)
---------------------------------
    python input_lock.py                 # locks the mouse for 3 seconds
    python input_lock.py --seconds 5     # locks for 5 seconds
    python input_lock.py --swallow move  # swallow only movement (clicks pass)
    python input_lock.py --pin           # hard-freeze the pointer via ClipCursor

Nothing here runs on import; everything happens inside main(), which only runs
when this file is executed directly.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as w
import sys
import threading
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.windll.kernel32

LRESULT = ctypes.c_ssize_t

# --- the same constants the (now removed) screenshot tool used ---
WH_MOUSE_LL = 14
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_MOUSEHWHEEL = 0x020E
WM_QUIT = 0x0012

# A hook procedure signature. argtypes must be set on the API calls or the
# 64-bit lParam overflows (that bug made an earlier tool raise on every event).
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, w.WPARAM, w.LPARAM)
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, w.HINSTANCE, w.DWORD]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, w.WPARAM, w.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.UnhookWindowsHookEx.restype = w.BOOL

MOVE_AND_CLICK = (WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP,
                  WM_RBUTTONDOWN, WM_RBUTTONUP, WM_MBUTTONDOWN, WM_MBUTTONUP,
                  WM_MOUSEWHEEL, WM_MOUSEHWHEEL, WM_XBUTTONDOWN, WM_XBUTTONUP)


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", w.POINT), ("mouseData", w.DWORD), ("flags", w.DWORD),
                ("time", w.DWORD), ("dwExtraInfo", ctypes.c_void_p)]


class MouseBlocker:
    """Installs a WH_MOUSE_LL hook on its own thread and swallows events."""

    def __init__(self, kinds: set[str]):
        # kinds: subset of {"move", "click"}; "all" == both
        self.catch_move = "all" in kinds or "move" in kinds
        self.catch_click = "all" in kinds or "click" in kinds
        self._proc = HOOKPROC(self._handler)   # keep a reference alive
        self._hook = None
        self._tid = 0
        self.blocked = 0                        # how many events we ate

    # The hook callback must be tiny: no Qt, no I/O, no blocking. Just decide
    # swallow-or-pass and return.
    def _handler(self, n_code, msg, l_param):
        if n_code < 0:
            return user32.CallNextHookEx(self._hook, n_code, msg, l_param)
        swallow = False
        if self.catch_move and msg == WM_MOUSEMOVE:
            swallow = True
        elif self.catch_click and msg in (WM_LBUTTONDOWN, WM_LBUTTONUP,
                                          WM_RBUTTONDOWN, WM_RBUTTONUP,
                                          WM_MBUTTONDOWN, WM_MBUTTONUP,
                                          WM_MOUSEWHEEL, WM_MOUSEHWHEEL,
                                          WM_XBUTTONDOWN, WM_XBUTTONUP):
            swallow = True
        if swallow:
            self.blocked += 1
            return 1                            # <-- the whole trick: drop it
        return user32.CallNextHookEx(self._hook, n_code, msg, l_param)

    def install(self):
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, None, 0)
        return self._hook is not None

    def uninstall(self):
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def run_until(self, stop_event: threading.Event):
        """Own message pump; exits when stop_event is set or WM_QUIT arrives."""
        self._tid = kernel32.GetCurrentThreadId()
        msg = w.MSG()
        while not stop_event.is_set():
            got = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if got == 0 or got == -1:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def stop(self):
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)


# ---------------------------------------------------------------------------
# Reference only: the documented API that blocks keyboard AND mouse at once.
# It is not used by main() because the keyboard must stay available as the
# escape hatch. Shown so the mechanism is complete.
# ---------------------------------------------------------------------------
def set_input_back(block: bool) -> bool:
    """user32.BlockInput: TRUE blocks all keyboard+mouse input for this session.
    Only the same thread/desktop can call it again with FALSE. Powerful and
    dangerous - the only way out is another process or a reboot."""
    user32.BlockInput.argtypes = [w.BOOL]
    user32.BlockInput.restype = w.BOOL
    return bool(user32.BlockInput(bool(block)))


# ---------------------------------------------------------------------------
# Hard freeze of movement: ClipCursor confines the pointer to a rectangle.
# ---------------------------------------------------------------------------
class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def clip_cursor_on():
    """Pin the pointer to its current position (a 1x1 clip rect). The pointer
    can no longer move; only releasing restores it."""
    user32.ClipCursor.argtypes = [ctypes.POINTER(RECT)]
    user32.ClipCursor.restype = w.BOOL
    p = w.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    r = RECT(p.x, p.y, p.x + 1, p.y + 1)
    return bool(user32.ClipCursor(ctypes.byref(r)))


def clip_cursor_off():
    """Release the clip rectangle (NULL) so the pointer moves freely again."""
    user32.ClipCursor(None)


class CursorPinner:
    """Keeps re-pinning the pointer, because some action (a driver, or a new
    foreground window) can clear the clip rect. A KeepAlive thread re-applies
    it until stopped. Release always clears the clip, with no user input."""

    def __init__(self, interval: float = 0.05):
        self.interval = interval
        self._stop = threading.Event()
        self._th = None

    def start(self):
        clip_cursor_on()
        self._th = threading.Thread(target=self._loop, daemon=True)
        self._th.start()

    def _loop(self):
        while not self._stop.is_set():
            clip_cursor_on()
            time.sleep(self.interval)

    def stop(self):
        self._stop.set()
        clip_cursor_off()
        if self._th:
            self._th.join(timeout=1.0)


def main():
    ap = argparse.ArgumentParser(description="Demonstrate a mouse-blocking hook "
                                             "(self-releasing, time-boxed).")
    ap.add_argument("--seconds", type=float, default=3.0,
                    help="how long to hold the lock (default 3)")
    ap.add_argument("--swallow", choices=["all", "move", "click"], default="all",
                    help="which events to swallow (default all)")
    ap.add_argument("--pin", action="store_true",
                    help="also hard-freeze the pointer with ClipCursor "
                         "(movement becomes impossible, not just slowed)")
    args = ap.parse_args()

    kinds = {"all"} if args.swallow == "all" else {args.swallow}
    blocker = MouseBlocker(kinds)
    pinner = CursorPinner() if args.pin else None

    print("QR Studio / input_lock demo")
    print(f"  swallowing: {args.swallow}   duration: {args.seconds}s"
          f"   pin pointer: {bool(args.pin)}")
    print("  escape: it releases by itself; Ctrl+C also aborts.")
    if input("  type GO and press Enter to arm (Ctrl+C to cancel): ").strip().upper() != "GO":
        print("cancelled.")
        return 0

    stop = threading.Event()
    if not blocker.install():
        print("SetWindowsHookExW failed:", ctypes.get_last_error())
        return 1

    th = threading.Thread(target=blocker.run_until, args=(stop,), daemon=True)
    th.start()
    if pinner:
        pinner.start()
    print(f"  LOCKED for {args.seconds}s (mouse only). Blocked so far:", end=" ", flush=True)

    try:
        end = time.monotonic() + args.seconds
        while time.monotonic() < end:
            time.sleep(0.25)
            print(blocker.blocked, end=" ", flush=True)
    except KeyboardInterrupt:
        print("\n  Ctrl+C - releasing early", flush=True)
    finally:
        # The release path takes no user input: release clip, unhook, stop pump.
        if pinner:
            pinner.stop()
        blocker.stop()
        blocker.uninstall()
        stop.set()
        th.join(timeout=1.0)
        print(f"\n  RELEASED. total events blocked: {blocker.blocked}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
