@echo off
cd /d "%~dp0"
echo Starting Gotham with local Ollama. No cloud usage or payments.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_windows.ps1" -Mode ollama
if errorlevel 1 (
 echo.
 echo Launch failed. Check that Python, Ollama and qwen2.5:1.5b are installed.
 pause
)
