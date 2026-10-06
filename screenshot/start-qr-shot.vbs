' QR Shot launcher (Windows) - runs in the BACKGROUND (no console window).
' Right-drag to capture. Quit with Ctrl+Alt+Q or the tray icon.
' Settings: tray icon -> Settings, or run settings_app.py.

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
shell.Run """" & pyw & """ """ & here & "\main.py""", 0, False
