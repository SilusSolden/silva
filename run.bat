@echo off
cd /d "%~dp0"
python main.py %*
if errorlevel 1 (
    echo.
    echo Silva exited with an error. See above for details.
    pause
)
