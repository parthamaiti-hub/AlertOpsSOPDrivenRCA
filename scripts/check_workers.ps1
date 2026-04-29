Write-Host "=== Docker Workers ===" -ForegroundColor Cyan
$dockerWorkers = docker ps --format "{{.Names}}\t{{.Status}}" 2>$null | Select-String "sopdrivenalertanalytics"
if ($dockerWorkers) {
    $dockerWorkers | ForEach-Object { Write-Host $_ }
} else {
    Write-Host "None running" -ForegroundColor DarkGray
}

Write-Host "`n=== Local Worker Processes ===" -ForegroundColor Cyan
$workerProcesses = Get-Process python* -ErrorAction SilentlyContinue | ForEach-Object {
    $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -ErrorAction SilentlyContinue).CommandLine
    if ($cmd -match "eventprocessing|identifySOP|executeSOP|validateRCA|main web") {
        [PSCustomObject]@{
            PID     = $_.Id
            Mode    = if ($cmd -match "eventprocessing") { "eventprocessing" }
                      elseif ($cmd -match "identifySOP") { "identifySOP" }
                      elseif ($cmd -match "executeSOP") { "executeSOP" }
                      elseif ($cmd -match "validateRCA") { "validateRCA" }
                      elseif ($cmd -match "main web") { "web" }
                      else { "unknown" }
        }
    }
}
if ($workerProcesses) {
    $workerProcesses | Format-Table -AutoSize
} else {
    Write-Host "None running" -ForegroundColor DarkGray
}

Write-Host "=== PowerShell Background Jobs (start_workers.ps1) ===" -ForegroundColor Cyan
$jobs = Get-Job -ErrorAction SilentlyContinue
if ($jobs) {
    $jobs | Format-Table Id, Name, State -AutoSize
} else {
    Write-Host "None running" -ForegroundColor DarkGray
}

Write-Host "--- Summary ---" -ForegroundColor Yellow
$dockerCount = if ($dockerWorkers) { @($dockerWorkers).Count } else { 0 }
$localCount  = if ($workerProcesses) { @($workerProcesses).Count } else { 0 }
Write-Host "Docker containers : $dockerCount"
Write-Host "Local processes   : $localCount"
if ($dockerCount -gt 0 -and $localCount -gt 0) {
    Write-Host "WARNING: Both Docker and local workers are running - duplicate consumers detected!" -ForegroundColor Red
}
