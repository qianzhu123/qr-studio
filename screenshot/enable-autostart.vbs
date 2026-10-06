' QR Shot - enable start at login (per user). Places a shortcut in the Startup
' folder that runs start-qr-shot.vbs in the background.

Option Explicit
Dim fso, shell, here, startup, lnk, target

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
startup = shell.SpecialFolders("Startup")

Set lnk = shell.CreateShortcut(startup & "\QR Shot.lnk")
lnk.TargetPath = "wscript.exe"
lnk.Arguments = """" & here & "\start-qr-shot.vbs"""
lnk.WorkingDirectory = here
lnk.Description = "QR Shot - right-drag screenshot tool"
lnk.Save

MsgBox "QR Shot will now start automatically at login." & vbCrLf & _
       "Shortcut: " & startup & "\QR Shot.lnk", 64, "QR Shot"
