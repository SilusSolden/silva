@echo off
cd /d "%~dp0"
set LOG=%USERPROFILE%\.silva\logs\silva.log
if exist "%LOG%" (
    notepad "%LOG%"
) else (
    echo No Silva log file yet. Run Silva and try a command first.
    echo Expected log path: %LOG%
    pause
)
