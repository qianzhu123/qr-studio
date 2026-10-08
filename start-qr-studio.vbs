' QR Studio - start the local web server in the BACKGROUND (no console window).
' Serves http://127.0.0.1:8788 . Double-click to start; open that URL in a browser.
' This file is used both manually and by the Startup shortcut.

Option Explicit
Dim fso, shell, here, pyw, candidates, i

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)

pyw = "pythonw"
candidates = Array( _
  "D:\tools\Dev\Runtime\Anaconda\pythonw.exe", _
  shell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"), _
  shell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"), _
  shell.ExpandEnvironmentStrings("%USERPROFILE%\anaconda3\pythonw.exe") )
For i = 0 To UBound(candidates)
  If fso.FileExists(candidates(i)) Then
    pyw = candidates(i)
    Exit For
  End If
Next

shell.CurrentDirectory = here
' 0 = hidden window; server.py prints its URL to stdout (discarded here)
shell.Run """" & pyw & """ """ & here & "\backend\server.py"" --port 8788", 0, False
