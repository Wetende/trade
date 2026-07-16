[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ExperimentalDemoRecord,
    [int]$PollSeconds = 30
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Launcher = Join-Path $Root "scripts\start-one-minute-experimental-demo.ps1"
$WorkerScript = Join-Path $Root (
    "scripts\one-minute-experimental-supervisor-worker.ps1"
)
$ExperimentalDemoRecord = (
    Resolve-Path -LiteralPath $ExperimentalDemoRecord
).Path
$RuntimeDir = Join-Path $Root "runtime\one-minute-experimental-supervisor"
$Heartbeat = Join-Path $RuntimeDir "heartbeat.json"
$Checkpoints = Join-Path $RuntimeDir "checkpoints.jsonl"
$Log = Join-Path $RuntimeDir "supervisor.log"
$PidFile = Join-Path $RuntimeDir "supervisor.pid"
$StopFile = Join-Path $RuntimeDir "supervisor.stop"

foreach ($Path in @($Python, $Launcher, $WorkerScript)) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Missing experimental supervisor dependency: $Path"
    }
}
if ($PollSeconds -lt 10 -or $PollSeconds -gt 300) {
    throw "PollSeconds must be between 10 and 300."
}

$Authorization = (
    Get-Content -LiteralPath $ExperimentalDemoRecord -Raw
) | ConvertFrom-Json
if (
    $Authorization.status -ne "EXPERIMENTAL_DEMO_ONLY" -or
    $Authorization.account_mode -ne "DEMO_ONLY" -or
    -not $Authorization.user_authorized -or
    [Math]::Abs([double]$Authorization.volume - 0.1) -gt 0.000000000001 -or
    [Math]::Abs(
        [double]$Authorization.max_session_loss_account_currency - 20.0
    ) -gt 0.000000000001 -or
    [Math]::Abs([double]$Authorization.max_session_hours - 3.0) -gt 0.000000000001
) {
    throw "The supervisor requires the frozen 0.1 DEMO authorization."
}
$Deadline = [DateTimeOffset]::Parse(
    [string]$Authorization.expires_at_utc
).ToUniversalTime()
if ($Deadline -le [DateTimeOffset]::UtcNow) {
    throw "The experimental authorization has expired."
}

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
if (Test-Path -LiteralPath $PidFile) {
    $ExistingPid = 0
    [void][int]::TryParse(
        (Get-Content -LiteralPath $PidFile -Raw).Trim(),
        [ref]$ExistingPid
    )
    if (
        $ExistingPid -gt 0 -and
        (Get-Process -Id $ExistingPid -ErrorAction SilentlyContinue)
    ) {
        throw "An experimental supervisor is already active with PID $ExistingPid."
    }
    Remove-Item -LiteralPath $PidFile -Force
}
foreach ($Path in @($StopFile, $Heartbeat)) {
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Force
    }
}

$Worker = Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $WorkerScript,
        "-Root",
        $Root,
        "-Python",
        $Python,
        "-Launcher",
        $Launcher,
        "-ExperimentalDemoRecord",
        $ExperimentalDemoRecord,
        "-RuntimeDir",
        $RuntimeDir,
        "-DeadlineUtc",
        $Deadline.ToString("o"),
        "-PollSeconds",
        [string]$PollSeconds
    ) `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -PassThru
$Worker.Id | Set-Content -LiteralPath $PidFile -Encoding ASCII

for ($Attempt = 1; $Attempt -le 40; $Attempt++) {
    Start-Sleep -Seconds 1
    if ($Worker.HasExited) {
        throw "The experimental supervisor exited during startup. Inspect $Log."
    }
    if (Test-Path -LiteralPath $Heartbeat) {
        $Status = (
            Get-Content -LiteralPath $Heartbeat -Raw
        ) | ConvertFrom-Json
        if ($Status.failed) {
            throw "The experimental supervisor failed: $($Status.reason)"
        }
        break
    }
}
if (-not (Test-Path -LiteralPath $Heartbeat)) {
    throw "The experimental supervisor did not write a startup heartbeat."
}

[ordered]@{
    process_id = $Worker.Id
    active = $true
    deadline_utc = $Deadline.ToString("o")
    volume = 0.1
    max_session_hours = 3.0
    max_session_loss = 20.0
    strategy_mutation_enabled = $false
    automatic_promotion_enabled = $false
    heartbeat_path = $Heartbeat
    checkpoints_path = $Checkpoints
    log_path = $Log
    stop_file = $StopFile
} | ConvertTo-Json
