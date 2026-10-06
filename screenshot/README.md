"""QR Shot - safe screenshot tool with annotation and local QR decode.

A small always-available utility living alongside QR Studio.

Trigger (hook-free by design)
- Global hotkey (default Ctrl+Alt+Q; env QR_SHOT_HOTKEY) via Win32
  RegisterHotKey.
- Right-button drag detected by POLLING GetAsyncKeyState + GetCursorPos on a
  15 ms Qt timer.
- Neither installs a low-level mouse hook, so neither can stall or freeze
  mouse/keyboard input. A plain right click is never touched, so its context
  menu still appears.

Flow
- Hotkey or right-drag -> frozen full-screen overlay.
- The right-drag continues the same region; inside the overlay a left-drag can
  also draw the region.
- On release the raw region is AUTO-COPIED to the clipboard.
- Annotate (rect, arrow, pen, highlight, mosaic, numbering, text), then
  Copy / Save / Pin / Decode. Decode shows type, content and detected
  symbology in a small card, with an optional HEAD-only redirect trace.
- Click outside the selection hides the toolbar. Pinned images close on
  double click.

History note
- An earlier version used a WH_MOUSE_LL low-level hook and repeatedly wedged
  system input on this machine. That path is abandoned. This tool deliberately
  uses only a polling watcher and a registered hotkey.

Files
- poll_watch.py  right-drag detection by polling (no hook)
- overlay.py     frozen-screen selection overlay, annotation shapes, pin window
- main.py        tray app, wiring, decode popup
- start-qr-shot.vbs   hidden-window launcher
- stop-qr-shot.vbs    emergency stop

Run
    python screenshot/main.py          (or double-click start-qr-shot.vbs)

Notes
- Coordinates are physical pixels (Per-Monitor DPI aware); grabWindow takes
  device pixels, so region grabs multiply by the screen DPR.
"""
