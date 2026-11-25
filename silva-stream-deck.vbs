Option Explicit
' Stream Deck XL: System → Open → this file (no extra cmd flash).
' Starts Silva with a visible window, or brings that window forward if Silva is already running.
Dim sh, fso
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
sh.CurrentDirectory = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run "pythonw -m silva.launch", 0, False
