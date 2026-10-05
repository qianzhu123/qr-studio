' QR Shot launcher (Windows)
' Starts the right-drag screenshot tool in a hidden window.
' Right-drag on screen to capture. Quit from the tray icon.

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
