import ctypes, ctypes.wintypes as w
u=ctypes.windll.user32; k=ctypes.windll.kernel32
def name_str(handle, getter):
    buf=ctypes.create_unicode_buffer(256); n=w.DWORD(0)
    getter(handle, buf, 256, ctypes.byref(n))
    return buf.value
ws = u.GetProcessWindowStation()
td = u.GetThreadDesktop(k.GetCurrentThreadId())
print("process window station:", name_str(ws, u.GetUserObjectInformationW) if False else None)
# GetUserObjectInformation UOI_NAME=2
UOI_NAME=2
def getname(h):
    buf=ctypes.create_unicode_buffer(256); need=w.DWORD(0)
    ok=u.GetUserObjectInformationW(h, UOI_NAME, buf, ctypes.sizeof(buf), ctypes.byref(need))
    return buf.value if ok else f"(err {ctypes.get_last_error()})"
print("window station:", getname(ws))
print("desktop        :", getname(td))
print("session id     :", ctypes.c_ulong(0).value)
pid=k.GetCurrentProcessId()
sid=ctypes.c_ulong(0)
k.ProcessIdToSessionId(pid, ctypes.byref(sid))
print("my pid:", pid, "session:", sid.value)
