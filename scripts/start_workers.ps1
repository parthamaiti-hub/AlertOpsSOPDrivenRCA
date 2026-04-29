Set-Location (Split-Path $PSScriptRoot)

$rootDir = (Get-Location).Path
$jobFile = Join-Path $rootDir "scripts\.worker_jobs.json"

# Check if workers are already running
if (Test-Path $jobFile) {
    $existing = Get-Content $jobFile | ConvertFrom-Json
    $alive = $existing | Where-Object { Get-Job -Id $_.Id -ErrorAction SilentlyContinue }
    if ($alive) {
        Write-Host "Workers already running. Run stop_workers.ps1 first."
        exit 1
    }
}

$workers = @(
    @{ Name = "web";             Args = "web" }
    @{ Name = "eventprocessing"; Args = "eventprocessing" }
    @{ Name = "identifySOP";     Args = "identifySOP" }
    @{ Name = "executeSOP";      Args = "executeSOP" }
    @{ Name = "validateRCA";     Args = "validateRCA" }
)

$jobs = @()

foreach ($w in $workers) {
    $logFile = Join-Path $rootDir "app_logs_$($w.Name).txt"
    $job = Start-Job -Name $w.Name -ScriptBlock {
        param($dir, $mode, $log)
        Set-Location $dir
        & uv run python -m backend.main $mode *>&1 | Tee-Object -FilePath $log -Append
    } -ArgumentList $rootDir, $w.Args, $logFile

    $jobs += @{ Id = $job.Id; Name = $w.Name; Log = $logFile }
    Write-Host "Started $($w.Name) (Job ID: $($job.Id))  ->  $logFile"
}

$jobs | ConvertTo-Json | Set-Content $jobFile
Write-Host ""
Write-Host "All 5 workers started. Use 'scripts\stop_workers.ps1' to stop them."
Write-Host "Logs: app_logs_<worker>.txt in project root"
