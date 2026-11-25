@echo off
REM Silva System Panel — GUI only (no black console window).
REM Safe to click while main Silva is already running.

cd /d "%~dp0"

where pythonw >nul 2>&1
if errorlevel 1 (
    start "" python main.py --dev-panel
    exit /b 0
)

start "" pythonw main.py --dev-panel
exit /b 0
