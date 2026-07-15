[CmdletBinding()]
param(
    [int]$PollSeconds = 60,
    [int]$MaxCycles = 10080
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$OutputDir = Join-Path $Root "runtime\demo-read-only-monitor"
$Heartbeat = Join-Path $OutputDir "heartbeat.json"
$Log = Join-Path $OutputDir "monitor.log"
$StopFile = Join-Path $OutputDir "monitor.stop"
$PidFile = Join-Path $OutputDir "monitor.pid"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python virtual environment not found: $Python"
}
if ($PollSeconds -lt 60) {
    throw "PollSeconds must be at least 60."
}
if ($MaxCycles -lt 1) {
    throw "MaxCycles must be positive."
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
if (Test-Path -LiteralPath $PidFile) {
    $ExistingPid = 0
    [void][int]::TryParse((Get-Content -LiteralPath $PidFile -Raw).Trim(), [ref]$ExistingPid)
    if ($ExistingPid -gt 0 -and (Get-Process -Id $ExistingPid -ErrorAction SilentlyContinue)) {
        throw "A read-only DEMO monitor is already active with PID $ExistingPid."
    }
    Remove-Item -LiteralPath $PidFile -Force
}
if (Test-Path -LiteralPath $StopFile) {
    Remove-Item -LiteralPath $StopFile -Force
}
if (Test-Path -LiteralPath $Heartbeat) {
    Remove-Item -LiteralPath $Heartbeat -Force
}

$WorkerScript = @"
`$ErrorActionPreference = "Continue"
Set-Location -LiteralPath "$Root"
`$env:TRADINGAGENTS_REQUIRE_DEMO_ACCOUNT = "true"
`$env:TRADINGAGENTS_MT5_ALLOW_REAL_ORDERS = "false"
`$Python = "$Python"
`$Heartbeat = "$Heartbeat"
`$Log = "$Log"
`$StopFile = "$StopFile"
`$PidFile = "$PidFile"
`$PollSeconds = $PollSeconds
`$MaxCycles = $MaxCycles

try {
    for (`$Cycle = 1; `$Cycle -le `$MaxCycles; `$Cycle++) {
        if (Test-Path -LiteralPath `$StopFile) {
            Add-Content -LiteralPath `$Log -Value (([DateTimeOffset]::UtcNow.ToString("o")) + " STOP_FILE cycle=" + `$Cycle)
            break
        }
        `$Lines = & `$Python -m cli.main broker-probe --json-only 2>&1
        `$Code = `$LASTEXITCODE
        `$Now = [DateTimeOffset]::UtcNow.ToString("o")
        `$Healthy = `$false
        `$Probe = `$null
        `$Reason = `$null
        if (`$Code -eq 0) {
            try {
                `$Probe = (`$Lines -join [Environment]::NewLine) | ConvertFrom-Json
                `$Healthy = (
                    `$Probe.connected -and
                    `$Probe.account_safety.passed -and
                    `$Probe.account_safety.trade_mode -eq "DEMO" -and
                    `$Probe.open_order_count -eq 0 -and
                    `$Probe.open_position_count -eq 0
                )
                if (-not `$Healthy) {
                    `$Reason = "DEMO_SAFETY_OR_FLAT_STATE_FAILED"
                }
            } catch {
                `$Reason = "PROBE_JSON_PARSE_FAILED: " + `$_.Exception.Message
            }
        } else {
            `$Reason = "BROKER_PROBE_EXIT_" + `$Code
        }
        `$Payload = [ordered]@{
            schema_version = 1
            heartbeat_utc = `$Now
            cycle = `$Cycle
            healthy = `$Healthy
            reason = `$Reason
            monitor_mode = "READ_ONLY_DEMO_CONNECTIVITY"
            broker_mutation_enabled = `$false
            probe = `$Probe
        }
        `$Temporary = `$Heartbeat + ".tmp"
        `$Payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath `$Temporary -Encoding UTF8
        Move-Item -LiteralPath `$Temporary -Destination `$Heartbeat -Force
        Add-Content -LiteralPath `$Log -Value (`$Now + " cycle=" + `$Cycle + " healthy=" + `$Healthy + " reason=" + `$Reason)
        if (-not `$Healthy) {
            break
        }
        Start-Sleep -Seconds `$PollSeconds
    }
} finally {
    Remove-Item -LiteralPath `$PidFile -Force -ErrorAction SilentlyContinue
}
"@

$Encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($WorkerScript))
$Worker = Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", $Encoded) `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -PassThru
$Worker.Id | Set-Content -LiteralPath $PidFile -Encoding ASCII

for ($Attempt = 1; $Attempt -le 10; $Attempt++) {
    Start-Sleep -Seconds 1
    if ($Worker.HasExited) {
        throw "The read-only DEMO monitor exited during startup. Inspect $Log."
    }
    if (Test-Path -LiteralPath $Heartbeat) {
        $Status = Get-Content -LiteralPath $Heartbeat -Raw | ConvertFrom-Json
        if (-not $Status.healthy) {
            throw "The read-only DEMO monitor failed its safety probe: $($Status.reason)"
        }
        break
    }
}
if (-not (Test-Path -LiteralPath $Heartbeat)) {
    throw "The read-only DEMO monitor did not write a startup heartbeat."
}

[ordered]@{
    process_id = $Worker.Id
    active = $true
    monitor_mode = "READ_ONLY_DEMO_CONNECTIVITY"
    broker_mutation_enabled = $false
    heartbeat_path = $Heartbeat
    log_path = $Log
    stop_file = $StopFile
    poll_seconds = $PollSeconds
    max_cycles = $MaxCycles
} | ConvertTo-Json
