# Live progress for the full ColorData generation run.
#
# Reads the profile cache directly rather than a log, because the cache is
# fixed-size records: bytes / record size = textures completed. That makes
# progress readable no matter how the run was launched, and it survives the
# run being restarted.
#
#   powershell -ExecutionPolicy Bypass -File tools\watch_run.ps1
#
# Ctrl+C to stop watching. This does NOT stop the run.

$ErrorActionPreference = "Stop"
$tools = Split-Path -Parent $MyInvocation.MyCommand.Path

# Record layout from generate_color_data.py: 3 x uint32 + 373 x float64.
$recordSize = 3 * 4 + 373 * 8
# Unique (texture, model, slot index) pairs across all 63,767 resolvable
# appearances -- slightly more than the 91,483 unique textures, since one
# texture can be weighted by more than one model.
$totalTextures = 95745

function Get-CacheFile {
    Get-ChildItem (Join-Path $tools "profile_cache_*.bin") -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
}

$startCount = $null
$startTime = Get-Date

while ($true) {
    $file = Get-CacheFile
    if (-not $file) {
        Write-Host "waiting for the run to create its profile cache..."
        Start-Sleep -Seconds 5
        continue
    }

    $done = [math]::Floor($file.Length / $recordSize)
    if ($null -eq $startCount) { $startCount = $done }

    $elapsed = ((Get-Date) - $startTime).TotalSeconds
    $rate = if ($elapsed -gt 5) { ($done - $startCount) / $elapsed } else { 0 }
    $pct = [math]::Round(100 * $done / $totalTextures, 2)

    $running = @(Get-Process python -ErrorAction SilentlyContinue).Count -gt 0
    $state = if ($running) { "running" } else { "NO PYTHON PROCESS - run has stopped" }

    $line = "{0,7:N0} / {1:N0} textures  ({2,5}%)  {3,5:N1}/s  {4}" -f `
        $done, $totalTextures, $pct, $rate, $state

    if ($rate -gt 0.05) {
        $etaHours = ($totalTextures - $done) / $rate / 3600
        $line += ("  ETA {0:N1}h (~{1:HH:mm})" -f $etaHours, (Get-Date).AddHours($etaHours))
    }

    Write-Host $line
    Start-Sleep -Seconds 30
}
