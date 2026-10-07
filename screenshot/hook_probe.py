import ctypes, ctypes.wintypes as w, time
import mouse_hook as M
M._DBG = open("probe.log","w",encoding="utf-8")
h=M.MouseHook(threshold=6); h._proc and None
# install on THIS thread's pump
import threading
th=threading.Thread(target=h.run, daemon=True); th.start()
time.sleep(0.8)
M._DBG.write("ready\n"); M._DBG.flush()
print("installed:", h._hook is not None, "- right-drag now for 25s", flush=True)
time.sleep(25)
h.stop()
M._DBG.close()
print("done", flush=True)
