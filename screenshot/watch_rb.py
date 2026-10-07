import ctypes, time
u = ctypes.windll.user32; u.GetAsyncKeyState.restype = ctypes.c_short
prev = False
print("ready: right-click/drag any time", flush=True)
while True:
    rb = bool(u.GetAsyncKeyState(0x02) & 0x8000)
    if rb != prev:
        p = ctypes.wintypes.POINT(); u.GetCursorPos(ctypes.byref(p))
        print(("RIGHT-DOWN" if rb else "RIGHT-UP  ") + f" @({p.x},{p.y})", flush=True)
        prev = rb
    time.sleep(0.005)
