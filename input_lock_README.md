# Input Lock (demo)

A small, self-releasing "input lock" demonstration for Windows. It shows how a
low-level hook can stop the mouse (and optionally the keyboard), with a design
that makes a stuck state impossible.

This is a teaching/demo tool. The interesting part is *why it is safe*, which is
also why the escape hatch is built in.

## What it does

- **Mouse**: a `WH_MOUSE_LL` hook swallows button and wheel events; an optional
  `ClipCursor` pin hard-freezes the pointer so it cannot move at all.
- **Keyboard** (optional): a `WH_KEYBOARD_LL` hook swallows every key **except**
  Ctrl and C, so the console always receives Ctrl+C.

## Why it cannot lock you out

A lock that depends on the locked input is a trap. Three independent guarantees
release it with **no user input required**:

1. a wall-clock timer releases at the chosen duration;
2. a watchdog thread releases at duration + 1s, even if the main loop crashes;
3. killing the process drops the hooks, and Windows resets `ClipCursor`.

With `--keyboard`, Ctrl and C are never swallowed, so Ctrl+C still reaches the
console: the **first** press only prints a reminder, the **second** releases.

## Files

| File | Role |
|------|------|
| `input_lock.py` | CLI: the lock primitives and a scriptable demo |
| `input_lock_gui.py` | GUI window (PySide6): pick what to lock and a duration |
| `input_lock_app.py` | windowed entry point (no console) used for freezing |
| `input_lock.spec` | PyInstaller spec: builds a single windowed `.exe` |

## CLI

```bash
python input_lock.py --pin --seconds 4              # freeze the pointer 4s
python input_lock.py --keyboard --pin --seconds 6   # also lock keys (Ctrl+C passes)
python input_lock.py --swallow move                 # movement only
```

## GUI

```bash
python input_lock_gui.py        # or: python input_lock_app.py
```

Check what to lock, set a duration (hours / minutes / seconds, sub-second precision, no cap), press **ARM** and confirm.
A countdown shows the remaining time; the lock releases automatically.

## Build the .exe (no console window)

```bash
python -m PyInstaller input_lock.spec --noconfirm
# result: dist/InputLock.exe   (PE subsystem GUI, so no terminal appears)
```

The `.exe` is windowed (`console=False`), so double-clicking it opens the GUI
with no terminal.

## Notes

- Nothing runs on import; the CLI demo requires typing `GO` to arm, and the GUI
  requires a confirmation dialog.
- The keyboard lock has no key-based way out (by design - a keyboard you can
  escape from is not locked); use a bounding duration.
- Built for Windows only.
