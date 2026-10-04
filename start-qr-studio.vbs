' QR Studio launcher (Windows)
' Double-click to run.
'
' Logic:
'   1. Check whether the server is already listening on the port.
'   2. If it is running  -> stop that exact process, then restart it.
'      If it is not running -> start it.
'   3. Wait for the port, then open the browser.
'
' The stop step kills only the PID that owns the port, so unrelated pythonw
' processes are left alone.

Option Explicit

Dim fso, shell, here, port, url, pyw, candidates, i, pid

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

' --- 1. is it already running? ---
pid = PidOnPort(port)

If pid <> "" Then
  ' --- 2a. running -> stop it ---
  shell.Run "taskkill /F /PID " & pid, 0, True
  ' wait until the port is actually free (max ~10s)
  For i = 1 To 40
    WScript.Sleep 250
    If PidOnPort(port) = "" Then Exit For
  Next
  If PidOnPort(port) <> "" Then
    MsgBox "Could not stop the existing server on port " & port & ".", 48, "QR Studio"
    WScript.Quit 1
  End If
End If

' --- 2b. start it (fresh) ---
shell.CurrentDirectory = here
shell.Run """" & pyw & """ """ & here & "\backend\server.py"" --port " & port, 0, False

' --- 3. wait for the port, then open the browser (max ~20s) ---
For i = 1 To 40
  WScript.Sleep 500
  If PidOnPort(port) <> "" Then
    shell.Run url, 1, False
    WScript.Quit 0
  End If
Next

MsgBox "QR Studio did not start in time." & vbCrLf & _
       "Try running it manually:" & vbCrLf & _
       "  python backend\server.py", 48, "QR Studio"
WScript.Quit 1


' Return the PID listening on the given port, or "" if none.
' Matches netstat -ano lines whose local address ends with :<port>.
Function PidOnPort(p)
  Dim exec, line, addr, pos, n, sep
  PidOnPort = ""
  On Error Resume Next
  Set exec = shell.Exec(shell.ExpandEnvironmentStrings("%comspec%") & " /c netstat -ano")
  Do While Not exec.StdOut.AtEndOfStream
    line = exec.StdOut.ReadLine
    If InStr(line, "LISTENING") > 0 Then
      pos = InStr(line, ":" & p & " ")
      If pos = 0 Then pos = InStr(line, ":" & p & Chr(9))
      If pos > 0 Then
        ' trailing token after the last run of spaces is the PID
        line = Trim(line)
        n = Len(line)
        Do While n > 0 And Mid(line, n, 1) <> " " And Mid(line, n, 1) <> Chr(9)
          n = n - 1
        Loop
        PidOnPort = Trim(Mid(line, n + 1))
        Exit Do
      End If
    End If
  Loop
  On Error GoTo 0
End Function
