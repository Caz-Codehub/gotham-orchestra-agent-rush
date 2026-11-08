# Starts no cloud resources and performs no shell/browser/Docker tool executions.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$python = '.\.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Error 'Start Gotham once using scripts\start_windows.ps1 -Mode ollama to install the local Python environment.'
    exit 2
}
$env:GOTHAM_INFERENCE_PROVIDER='ollama'
$env:GOTHAM_ALLOW_PAID_INFERENCE=''
if (-not $env:GOTHAM_OLLAMA_MODEL) { $env:GOTHAM_OLLAMA_MODEL='qwen2.5:1.5b' }
$env:GOTHAM_SPECTER_DB=Join-Path $env:LOCALAPPDATA 'GothamProject\specter.sqlite3'
Write-Host 'Local-only test. The Qwen model may take several minutes on a laptop.' -ForegroundColor Cyan
& $python scripts/prove_local_agents.py
exit $LASTEXITCODE
