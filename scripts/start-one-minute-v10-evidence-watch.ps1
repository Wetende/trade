[CmdletBinding()]
param(
    [int]$PollSeconds = 600,
    [int]$MaxCycles = 2016
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$WorkerScript = Join-Path $Root "scripts\watch-one-minute-v10.py"
$Runtime = Join-Path $Root "runtime\one-minute-v10-evidence"
$Heartbeat = Join-Path $Runtime "heartbeat.json"
$PidFile = Join-Path $Runtime "watch.pid"
$Stdout = Join-Path $Runtime "stdout.log"
$Stderr = Join-Path $Runtime "stderr.log"

if ($PollSeconds -lt 60 -or $MaxCycles -lt 1) {
    throw "Invalid V10 watcher bounds."
}
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
if (Test-Path -LiteralPath $PidFile) {
    $Existing = 0
    [void][int]::TryParse((Get-Content -LiteralPath $PidFile -Raw).Trim(), [ref]$Existing)
    if ($Existing -gt 0 -and (Get-Process -Id $Existing -ErrorAction SilentlyContinue)) {
        throw "A V10 evidence watcher is already active with PID $Existing."
    }
    Remove-Item -LiteralPath $PidFile -Force
}
foreach ($Path in @($Heartbeat, (Join-Path $Runtime "watch.stop"))) {
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Force
    }
}
$Worker = Start-Process `
    -FilePath $Python `
    -ArgumentList @($WorkerScript, "--root", $Root, "--poll-seconds", $PollSeconds, "--max-cycles", $MaxCycles) `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $Stdout `
    -RedirectStandardError $Stderr `
    -PassThru
$Worker.Id | Set-Content -LiteralPath $PidFile -Encoding ASCII
for ($Attempt = 1; $Attempt -le 20; $Attempt++) {
    Start-Sleep -Seconds 1
    if ($Worker.HasExited) {
        throw "The V10 evidence watcher exited during startup. Inspect $Stderr."
    }
    if (Test-Path -LiteralPath $Heartbeat) {
        $Status = Get-Content -LiteralPath $Heartbeat -Raw | ConvertFrom-Json
        if ($Status.status -eq "FAILED") {
            throw "The V10 evidence watcher failed: $($Status.reason)"
        }
        break
    }
}
if (-not (Test-Path -LiteralPath $Heartbeat)) {
    throw "The V10 evidence watcher did not write a startup heartbeat."
}
[ordered]@{
    process_id = $Worker.Id
    active = $true
    candidate = "ONE_MINUTE_CAUSAL_RECLAIM_V10"
    broker_mutation_enabled = $false
    heartbeat_path = $Heartbeat
    pid_path = $PidFile
    stdout_path = $Stdout
    stderr_path = $Stderr
    poll_seconds = $PollSeconds
    max_cycles = $MaxCycles
} | ConvertTo-Json
