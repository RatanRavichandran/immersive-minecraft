' Launches the sky-sync bridge silently in the background (no console
' window), with its working directory set to this file's own folder so
' its sibling-module imports (config, skymodel, bulb, listener) resolve
' the same way they do when run interactively.
'
' Meant to run once per Windows login via a copy/shortcut of this file in
' the Startup folder (shell:startup) - see TASKS.md for setup notes. Safe
' to double-click by hand too, any time: it just starts the bridge and
' exits immediately, leaving the bridge running in the background.
'
' Logs to bridge.log in this same folder - check there if the bulb never
' seems to respond after login. There's no supervisor here: if the bridge
' crashes, it stays down until the next login or a manual restart.

Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = scriptDir
shell.Run """" & scriptDir & "\.venv\Scripts\pythonw.exe"" main.py", 0, False
