# Gotham 2.1: read-only, privacy-conscious Windows hardware readiness summary.
# Do not need admin access. Does not install anything or contact the cloud.
$ErrorActionPreference = 'Stop'
Write-Host 'GOTHAM LOCAL HARDWARE CHECK (no cloud calls)' -ForegroundColor Cyan
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$gpus = @(Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name)
$ramGB = [Math]::Round(([double]$os.TotalVisibleMemorySize * 1KB) / 1GB, 1)
$freeGB = [Math]::Round(([double]$os.FreePhysicalMemory * 1KB) / 1GB, 1)
$systemDrive = Get-PSDrive -Name ($env:SystemDrive.TrimEnd(':')) -ErrorAction SilentlyContinue
$diskFreeGB = if ($systemDrive) { [Math]::Round($systemDrive.Free / 1GB, 1) } else { 'Unavailable' }
$ollamaInstalled = [bool](Get-Command ollama -ErrorAction SilentlyContinue)
$dockerInstalled = [bool](Get-Command docker -ErrorAction SilentlyContinue)
$localModels = @()
if ($ollamaInstalled) {
    try {
        $localModels = @((ollama list 2>$null | Select-Object -Skip 1) | Where-Object { $_ -notmatch '-cloud\s' -and $_ -notmatch ':cloud\s' })
    } catch { $localModels = @() }
}
Write-Output "CPU: $($cpu.Name)"
Write-Output "Installed RAM: $ramGB GB | Free RAM: $freeGB GB"
Write-Output "GPU(s): $($gpus -join '; ')"
Write-Output "Free space on system drive: $diskFreeGB GB"
Write-Output "Ollama available: $ollamaInstalled | Docker CLI available: $dockerInstalled"
Write-Output "Local model entries: $($localModels.Count)"
Write-Output 'This check did not install software, rent computing, or send data to an AI provider.'
Write-Output 'Do not share screenshots that show Gotham mission/audit tokens or other credentials.'
