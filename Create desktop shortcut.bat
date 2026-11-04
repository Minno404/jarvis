@echo off
cd /d "%~dp0"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\JARVIS.lnk'); $s.TargetPath='%~dp0Jarvis.bat'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0jarvis.ico'; $s.WindowStyle=7; $s.Save()"
echo JARVIS shortcut added to your desktop.
pause
