' QR Studio launcher (Windows)
' Starts the local server in a hidden window, then opens the browser.
' Double-click this file. Close the server with:  taskkill /IM pythonw.exe /F

Option Explicit

Dim fso, shell, here, port, url, pyw, candidates, i, req, tries

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

here = fso.GetParentFolderName(WScript.ScriptFullName)
port = 8788
url = "http://127.0.0.1:" & port & "/"

' --- resolve pythonw (no console window); fall back to bare name on PATH ---
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

' --- if the server is already up, just open the browser ---
If ServerIsUp(url) Then
  shell.Run url, 1, False
  WScript.Quit 0
End If

' --- launch the server hidden ---
shell.CurrentDirectory = here
shell.Run """" & pyw & """ """ & here & "\backend\server.py"" --port " & port, 0, False

' --- wait for the port, then open the browser (max ~20s) ---
For tries = 1 To 40
  WScript.Sleep 500
  If ServerIsUp(url) Then
    shell.Run url, 1, False
    WScript.Quit 0
  End If
Next

MsgBox "QR Studio did not start in time." & vbCrLf & _
       "Try running it manually:" & vbCrLf & _
       "  python backend\server.py", 48, "QR Studio"
WScript.Quit 1

' Return True if the server answers on the given URL.
Function ServerIsUp(u)
  Dim x
  ServerIsUp = False
  On Error Resume Next
  Set x = CreateObject("MSXML2.XMLHTTP")
  x.Open "GET", u, False
  x.Send
  If Err.Number = 0 Then
    If x.Status = 200 Then ServerIsUp = True
  End If
  On Error GoTo 0
End Function
