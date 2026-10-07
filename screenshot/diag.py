"""diag.py - diagnose whether polling can see the physical right button.

Runs for 25 seconds. Prints one line per state change of the right/left mouse
button and the cursor position, so we can tell whether GetAsyncKeyState sees a
real right-drag on this machine. No hook, read-only.
"""
import ctypes
import time

u = ctypes.windll.user32
u.GetAsyncKeyState.restype = ctypes.c_short
print("diag: watching right button for 25s. Do a right-DRAG now.", flush=True)

VK_R, VK_L = 0x02, 0x01
prev_r = prev_l = False
t0 = time.time()
last_report = t0
while time.time() - t0 < 25:
    rb = bool(u.GetAsyncKeyState(VK_R) & 0x8000)
    lb = bool(u.GetAsyncKeyState(VK_L) & 0x8000)
    if rb != prev_r:
        x, y = ctypes.c_long(), ctypes.c_long()
        class PT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        p = PT()
        u.GetCursorPos(ctypes.byref(p))
        print(f"{time.time()-t0:5.1f}s  RIGHT {'DOWN' if rb else 'UP  '}  @({p.x},{p.y})", flush=True)
        prev_r = rb
    if lb != prev_l:
        print(f"{time.time()-t0:5.1f}s  LEFT  {'DOWN' if lb else 'UP  '}", flush=True)
        prev_l = lb
    time.sleep(0.008)
print("diag: done.", flush=True)
