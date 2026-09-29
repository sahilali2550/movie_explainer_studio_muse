@echo off
cd /d "%~dp0"
if exist "%~dp0venv\Scripts\pythonw.exe" (
    start "" "%~dp0venv\Scripts\pythonw.exe" desktop_launcher.py
) else (
    start "" pythonw desktop_launcher.py
)
exit
