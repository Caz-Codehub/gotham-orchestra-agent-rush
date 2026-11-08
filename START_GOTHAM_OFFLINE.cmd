@echo off
cd /d "%~dp0"
echo Starting Gotham dashboard without model inference. This is NOT live AI reasoning.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_windows.ps1" -Mode offline
if errorlevel 1 pause
