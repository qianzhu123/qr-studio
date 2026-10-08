' QR Studio - enable "start at login".
' Creates a shortcut in the user's Startup folder that runs start-qr-studio.vbs
' in the background, so the local server is available after every boot.

Option Explicit
Dim fso, shell, here, startup, lnk

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
startup = shell.SpecialFolders("Startup")

Set lnk = shell.CreateShortcut(startup & "\QR Studio.lnk")
lnk.TargetPath = "wscript.exe"
lnk.Arguments = """" & here & "\start-qr-studio.vbs"""
lnk.WorkingDirectory = here
lnk.WindowStyle = 7
lnk.Description = "QR Studio local server"
lnk.Save

MsgBox "QR Studio will start automatically at login." & vbCrLf & vbCrLf & _
       "Shortcut: " & startup & "\QR Studio.lnk" & vbCrLf & _
       "Open http://127.0.0.1:8788 after logging in.", 64, "QR Studio"
