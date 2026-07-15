[CmdletBinding()]
param(
    [string]$SourceManifest = ".\docs\analysis\2026-07-15-one-minute-learning-sources.json",
    [int]$PollSeconds = 300,
    [int]$MaxCycles = 2016
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Manifest = (Resolve-Path -LiteralPath (Join-Path $Root $SourceManifest)).Path
$OutputDir = Join-Path $Root "runtime\one-minute-learning"
$Ledger = Join-Path $OutputDir "ledger.json"
$Heartbeat = Join-Path $OutputDir "heartbeat.json"
$Log = Join-Path $OutputDir "learning-watch.log"
$StopFile = Join-Path $OutputDir "learning-watch.stop"
$PidFile = Join-Path $OutputDir "learning-watch.pid"

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
        throw "A controlled M1 learning watcher is already active with PID $ExistingPid."
    }
    Remove-Item -LiteralPath $PidFile -Force
}
foreach ($Path in @($StopFile, $Heartbeat)) {
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Force
    }
}

$WorkerScript = @"
`$ErrorActionPreference = "Continue"
Set-Location -LiteralPath "$Root"
`$Python = "$Python"
`$Manifest = "$Manifest"
`$Ledger = "$Ledger"
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
        `$Lines = & `$Python -m cli.main one-minute-learn --source-manifest `$Manifest --output `$Ledger 2>&1
        `$Code = `$LASTEXITCODE
        `$Now = [DateTimeOffset]::UtcNow.ToString("o")
        `$Healthy = `$false
        `$Reason = `$null
        `$Summary = `$null
        `$LedgerSha256 = `$null
        if (`$Code -eq 0 -and (Test-Path -LiteralPath `$Ledger)) {
            try {
                `$Report = Get-Content -LiteralPath `$Ledger -Raw | ConvertFrom-Json
                `$Healthy = (
                    -not `$Report.broker_mutation_enabled -and
                    -not `$Report.live_rule_mutation_enabled -and
                    -not `$Report.automatic_promotion_enabled -and
                    -not `$Report.operational_permissions.place_or_modify_orders -and
                    -not `$Report.operational_permissions.authorize_demo_start
                )
                if (`$Healthy) {
                    `$Summary = `$Report.diagnostics.summary
                    `$LedgerSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath `$Ledger).Hash.ToLowerInvariant()
                } else {
                    `$Reason = "LEARNING_GUARDRAIL_FAILED"
                }
            } catch {
                `$Reason = "LEARNING_LEDGER_PARSE_FAILED: " + `$_.Exception.Message
            }
        } else {
            `$Reason = "LEARNING_COMMAND_EXIT_" + `$Code
        }
        `$Payload = [ordered]@{
            schema_version = 1
            heartbeat_utc = `$Now
            cycle = `$Cycle
            healthy = `$Healthy
            reason = `$Reason
            learning_mode = "OFFLINE_HYPOTHESIS_GENERATION_ONLY"
            broker_mutation_enabled = `$false
            live_rule_mutation_enabled = `$false
            automatic_promotion_enabled = `$false
            source_manifest = `$Manifest
            ledger_path = `$Ledger
            ledger_sha256 = `$LedgerSha256
            summary = `$Summary
        }
        `$Temporary = `$Heartbeat + ".tmp"
        `$Payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath `$Temporary -Encoding UTF8
        Move-Item -LiteralPath `$Temporary -Destination `$Heartbeat -Force
        Add-Content -LiteralPath `$Log -Value (`$Now + " cycle=" + `$Cycle + " healthy=" + `$Healthy + " reason=" + `$Reason)
        if (-not `$Healthy) {
            if (`$Lines) {
                Add-Content -LiteralPath `$Log -Value (`$Lines -join [Environment]::NewLine)
            }
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

for ($Attempt = 1; $Attempt -le 20; $Attempt++) {
    Start-Sleep -Seconds 1
    if ($Worker.HasExited) {
        throw "The controlled M1 learning watcher exited during startup. Inspect $Log."
    }
    if (Test-Path -LiteralPath $Heartbeat) {
        $Status = Get-Content -LiteralPath $Heartbeat -Raw | ConvertFrom-Json
        if (-not $Status.healthy) {
            throw "The controlled M1 learning watcher failed: $($Status.reason)"
        }
        break
    }
}
if (-not (Test-Path -LiteralPath $Heartbeat)) {
    throw "The controlled M1 learning watcher did not write a startup heartbeat."
}

[ordered]@{
    process_id = $Worker.Id
    active = $true
    learning_mode = "OFFLINE_HYPOTHESIS_GENERATION_ONLY"
    broker_mutation_enabled = $false
    live_rule_mutation_enabled = $false
    automatic_promotion_enabled = $false
    source_manifest = $Manifest
    ledger_path = $Ledger
    heartbeat_path = $Heartbeat
    log_path = $Log
    stop_file = $StopFile
    poll_seconds = $PollSeconds
    max_cycles = $MaxCycles
} | ConvertTo-Json
