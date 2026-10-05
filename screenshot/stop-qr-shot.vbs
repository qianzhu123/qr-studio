' QR Shot - stop / emergency kill
' Terminates any python/pythonw process running screenshot\main.py.
' Double-click this if the tool misbehaves and the tray is unreachable.

Option Explicit
Dim svc, procs, p, killed
Set svc = GetObject("winmgmts:\\.\root\cimv2")
Set procs = svc.ExecQuery("Select ProcessId, Name, CommandLine from Win32_Process " & _
                          "Where Name='pythonw.exe' or Name='python.exe'")
killed = 0
For Each p In procs
  If Not IsNull(p.CommandLine) Then
    If InStr(LCase(p.CommandLine), "screenshot") > 0 And _
       InStr(LCase(p.CommandLine), "main.py") > 0 Then
      p.Terminate()
      killed = killed + 1
    End If
  End If
Next
If killed = 0 Then
  ' Fallback: nothing matched, kill all pythonw (the launcher uses pythonw)
  Set procs = svc.ExecQuery("Select ProcessId from Win32_Process Where Name='pythonw.exe'")
  For Each p In procs
    p.Terminate()
    killed = killed + 1
  Next
End If
