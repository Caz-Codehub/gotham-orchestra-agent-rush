# Windows PowerShell / PowerShell 7. Run from the extracted Gotham project folder.
# No accounts, cloud provisioning, paid inference, or automatic model downloads.
param([ValidateSet('offline','ollama')][string]$Mode='offline')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
function New-Token {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
}
if (-not $env:GOTHAM_ACCESS_TOKEN) { $env:GOTHAM_ACCESS_TOKEN = New-Token }
if (-not $env:GOTHAM_BATMAN_TOKEN) { $env:GOTHAM_BATMAN_TOKEN = New-Token }
if ($Mode -eq 'ollama') {
    $env:GOTHAM_INFERENCE_PROVIDER='ollama'
    if (-not $env:GOTHAM_OLLAMA_MODEL) { $env:GOTHAM_OLLAMA_MODEL='qwen2.5:1.5b' }
} else { $env:GOTHAM_INFERENCE_PROVIDER='none' }
$env:GOTHAM_ALLOW_PAID_INFERENCE=''
$dataDir=Join-Path $env:LOCALAPPDATA 'GothamProject'
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
$env:GOTHAM_LEDGER_PATH=Join-Path $dataDir 'missions.sqlite3'
$env:GOTHAM_SPECTER_DB=Join-Path $dataDir 'specter.sqlite3'
$venv=Join-Path (Get-Location) '.venv'
$python=Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $python)) { python -m venv $venv }
& $python -m pip install --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Could not install local Python dependencies' }
& $python scripts/preflight.py --mode objective
if ($LASTEXITCODE -ne 0) { throw 'Preflight failed: in Ollama mode, start Ollama and download the selected local model first.' }
Write-Host ''
Write-Host 'GOTHAM PROJECT — LOCAL ZERO-CLOUD-CHARGE MODE' -ForegroundColor Cyan
Write-Host 'Open: http://127.0.0.1:8000' -ForegroundColor Green
Write-Host "MISSION TOKEN: $env:GOTHAM_ACCESS_TOKEN" -ForegroundColor Yellow
Write-Host "BATMAN AUDIT TOKEN: $env:GOTHAM_BATMAN_TOKEN" -ForegroundColor Yellow
Write-Host 'Treat these as passwords. Do not post them or include in a screenshot.'
Write-Host "Mode: $Mode. Code execution additionally requires Docker Desktop and cached python:3.12-alpine image."
Write-Host 'To enable local AI reasoning, run Ollama separately and pull qwen2.5:1.5b; no downloads are performed by this script.'
& $python -m uvicorn gotham.app:app --host 127.0.0.1 --port 8000 --workers 1
