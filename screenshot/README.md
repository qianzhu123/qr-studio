"""QR Shot - right-drag screenshot tool with annotation and QR decode.

A small always-available utility living alongside QR Studio.

Core behavior
- Right-button DRAG on the desktop opens a frozen-screen selection overlay.
  A plain right click still opens the normal context menu, so it does not get
  in the way of other apps.
- Select a region, annotate it, then copy / save / pin / decode.
- "Decode" runs the local QR/decode engine and shows the result (type, content,
  detected symbology) in a small card, with an optional HEAD-only redirect
  trace. Nothing is uploaded.

Why this exists
- Quicker-style trigger tools cause accidental captures and lack annotation.
  This offers an explicit right-drag gesture (no mis-trigger) with a real
  annotation toolbar.

Files
- mouse_hook.py  global low-level mouse hook (Win32, ctypes); detects right-drag
- overlay.py     frozen-screen selection overlay, annotation shapes, result popup
- main.py        tray app, wiring, decode popup
- start-qr-shot.vbs   hidden-window launcher
- stop-qr-shot.vbs    emergency stop (kills the screenshot process)

Safety model (important)
- The hook procedure does the minimum possible work: it appends an event to a
  queue and returns. It never touches Qt and never blocks, because a slow
  low-level hook stalls mouse input for the whole system.
- The hook is observe-only by default (`swallow=False`): it never blocks mouse
  events. A plain right click still opens the normal context menu.
- Qt polls the event queue on a timer, so all UI work happens on the main
  thread.
- A watchdog closes any overlay left open longer than 60 seconds.
- If anything goes wrong, run stop-qr-shot.vbs to kill the process.

Run
    python screenshot/main.py          (or double-click start-qr-shot.vbs)

Notes
- Coordinates are physical pixels (Per-Monitor DPI aware); grabWindow mapping is
  approximate under heavy mixed-DPI, verify on your setup.
- The hook swallows right-button events once a drag is detected, so other apps
  do not also react to the drag. A plain click is never swallowed.
- Toggle the hook from the tray menu (Enabled / Quit). Only one instance runs.
"""
