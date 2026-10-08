' QR Studio - start the local server silently (no console window).
' Absolute paths are used so this file works from anywhere, including the
' Startup folder. Double-click to start; open http://127.0.0.1:8788 in a browser.

Option Explicit
Dim shell, SERVER_DIR, PYTHONW, SERVER_PY

SERVER_DIR = "D:\code\myweb\qr-studio"
PYTHONW    = "D:\tools\Dev\Runtime\Anaconda\pythonw.exe"
SERVER_PY  = SERVER_DIR & "\backend\server.py"

Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = SERVER_DIR
shell.Run """" & PYTHONW & """ """ & SERVER_PY & """ --port 8788", 0, False
