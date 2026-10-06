' QR Shot - disable start at login (removes the Startup shortcut).

Option Explicit
Dim shell, startup, p
Set shell = CreateObject("WScript.Shell")
startup = shell.SpecialFolders("Startup")
p = startup & "\QR Shot.lnk"
If CreateObject("Scripting.FileSystemObject").FileExists(p) Then
  CreateObject("Scripting.FileSystemObject").DeleteFile p
  MsgBox "QR Shot will no longer start at login.", 64, "QR Shot"
Else
  MsgBox "No startup shortcut found.", 64, "QR Shot"
End If
