import ctypes, ctypes.wintypes as w, time
u=ctypes.WinDLL("user32",use_last_error=True); k=ctypes.windll.kernel32
LRESULT=ctypes.c_ssize_t
HP=ctypes.WINFUNCTYPE(LRESULT,ctypes.c_int,w.WPARAM,w.LPARAM)
u.SetWindowsHookExW.argtypes=[ctypes.c_int,HP,w.HINSTANCE,w.DWORD]; u.SetWindowsHookExW.restype=ctypes.c_void_p
u.CallNextHookEx.argtypes=[ctypes.c_void_p,ctypes.c_int,w.WPARAM,w.LPARAM]; u.CallNextHookEx.restype=LRESULT
class MS(ctypes.Structure):
    _fields_=[("pt",w.POINT),("md",w.DWORD),("fl",w.DWORD),("t",w.DWORD),("x",ctypes.c_void_p)]
NAMES={0x0200:"MOVE",0x0201:"LDOWN",0x0202:"LUP",0x0204:"RDOWN",0x0205:"RUP",0x0206:"RDBL",0x0207:"MDBL",0x0208:"MDOWN",0x0209:"MUP",0x020A:"WHEEL",0x020E:"HWHEEL"}
log=open("hook_events.log","w",encoding="utf-8")
def handler(n,w_,l):
    if n==0:
        try:
            if w_ in NAMES:
                info=ctypes.cast(l,ctypes.POINTER(MS)).contents
                log.write(f"{time.time():.3f} {NAMES[w_]} @({info.pt.x},{info.pt.y})\n"); log.flush()
        except Exception: pass
    return u.CallNextHookEx(None,n,w_,l)
cb=HP(handler)
h=u.SetWindowsHookExW(14,cb,None,0)
log.write("ready\n"); log.flush()
print("hook ready, logging 20s" if h else "HOOK FAILED", flush=True)
msg=w.MSG(); end=time.time()+20
while time.time()<end:
    if u.PeekMessageW(ctypes.byref(msg),None,0,0,1):
        u.TranslateMessage(ctypes.byref(msg)); u.DispatchMessageW(ctypes.byref(msg))
    time.sleep(0.005)
log.write("done\n"); log.close()
print("done", flush=True)
