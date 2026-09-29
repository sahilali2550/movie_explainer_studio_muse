Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strDir

pythonwExe = strDir & "\venv\Scripts\pythonw.exe"
If Not fso.FileExists(pythonwExe) Then
    pythonwExe = "pythonw.exe"
End If

WshShell.Run """" & pythonwExe & """ """ & strDir & "\desktop_launcher.py""", 0, False
