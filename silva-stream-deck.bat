@echo off
REM Stream Deck XL: System → Open → this file.
REM Starts Silva with a visible window, or brings that window forward if Silva is already running.
cd /d "%~dp0"
where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw -m silva.launch
) else (
    start "" python -m silva.launch
)
