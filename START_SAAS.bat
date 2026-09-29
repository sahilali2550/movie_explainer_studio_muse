@echo off
title AutoExplainer AI SaaS - Engine Runner
color 0B
echo ============================================================
echo   🎬 AUTOEXPLAINER AI SAAS ENGINE
echo   Standalone Clean SaaS Platform
echo ============================================================
echo.

cd /d "%~dp0backend"

:: Use dedicated venv python if available, else system python
if exist "%~dp0venv\Scripts\python.exe" (
    "%~dp0venv\Scripts\python.exe" run_server.py
) else (
    python run_server.py
)

pause
