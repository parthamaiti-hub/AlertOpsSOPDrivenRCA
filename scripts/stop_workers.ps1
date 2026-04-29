Set-Location (Split-Path $PSScriptRoot)

$rootDir = (Get-Location).Path
$jobFile = Join-Path $rootDir "scripts\.worker_jobs.json"

$stopped = 0

# Step 1: Discover local worker processes (regardless of how they were started)
Write-Host "=== Checking local worker processes ===" -ForegroundColor Cyan
$workerProcesses = Get-Process python* -ErrorAction SilentlyContinue | ForEach-Object {
    $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -ErrorAction SilentlyContinue).CommandLine
    if ($cmd -match "eventprocessing|identifySOP|executeSOP|validateRCA|main web") {
        [PSCustomObject]@{ PID = $_.Id; Command = $cmd }
    }
}

if ($workerProcesses) {
    foreach ($proc in $workerProcesses) {
        $mode = if ($proc.Command -match "eventprocessing") { "eventprocessing" }
                elseif ($proc.Command -match "identifySOP")  { "identifySOP" }
                elseif ($proc.Command -match "executeSOP")   { "executeSOP" }
                elseif ($proc.Command -match "validateRCA")  { "validateRCA" }
                elseif ($proc.Command -match "main web")     { "web" }
                else { "worker" }
        Write-Host "Stopping process: $mode (PID: $($proc.PID))"
        Stop-Process -Id $proc.PID -Force -ErrorAction SilentlyContinue
        $stopped++
    }
} else {
    Write-Host "No local worker processes found." -ForegroundColor DarkGray
}

# Step 2: Stop PowerShell background jobs from start_workers.ps1
Write-Host "`n=== Checking PowerShell background jobs ===" -ForegroundColor Cyan
if (Test-Path $jobFile) {
    $jobs = Get-Content $jobFile | ConvertFrom-Json
    foreach ($j in $jobs) {
        $job = Get-Job -Id $j.Id -ErrorAction SilentlyContinue
        if ($job) {
            Stop-Job -Id $j.Id
            Remove-Job -Id $j.Id
            Write-Host "Stopped job: $($j.Name) (Job ID: $($j.Id))"
            $stopped++
        } else {
            Write-Host "Job already gone: $($j.Name) (Job ID: $($j.Id))" -ForegroundColor DarkGray
        }
    }
    Remove-Item $jobFile -Force
} else {
    # Also check for any lingering worker-named jobs not tracked by file
    $namedJobs = Get-Job -ErrorAction SilentlyContinue | Where-Object { $_.Name -match "worker_" }
    if ($namedJobs) {
        foreach ($job in $namedJobs) {
            Stop-Job -Id $job.Id
            Remove-Job -Id $job.Id
            Write-Host "Stopped job: $($job.Name) (Job ID: $($job.Id))"
            $stopped++
        }
    } else {
        Write-Host "No background jobs found." -ForegroundColor DarkGray
    }
}

Write-Host ""
if ($stopped -gt 0) {
    Write-Host "Stopped $stopped worker(s)." -ForegroundColor Green
} else {
    Write-Host "No workers were running." -ForegroundColor Yellow
}
