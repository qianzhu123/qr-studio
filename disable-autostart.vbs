' QR Studio - disable "start at login" (removes the Startup shortcut).

Option Explicit
Dim fso, shell, startup, p
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
startup = shell.SpecialFolders("Startup")
p = startup & "\QR Studio.lnk"
If fso.FileExists(p) Then
  fso.DeleteFile p
  MsgBox "QR Studio will no longer start at login.", 64, "QR Studio"
Else
  MsgBox "No startup shortcut was found.", 64, "QR Studio"
End If
