param(
    [string]$ProspectiveStart = "2026-07-03T11:25:00+00:00",
    [string]$SessionName = "2026-07-03-112500-target-grid-shadow",
    [string]$ManifestPath = "",
    [int]$PollSeconds = 3600,
    [int]$MaxCycles = 72,
    [switch]$Foreground
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$DefaultManifest = Join-Path $Root "docs\analysis\2026-07-03-one-minute-opening-state-target-grid-frozen-manifest.json"
$Manifest = if ($ManifestPath) {
    (Resolve-Path -LiteralPath $ManifestPath).Path
} else {
    $DefaultManifest
}
$OutputDir = Join-Path $Root ("test-artifacts\opening-state-shadow\" + $SessionName)
$Report = Join-Path $OutputDir "shadow-report.json"
$Heartbeat = Join-Path $OutputDir "shadow-heartbeat.json"
$Stdout = Join-Path $OutputDir "stdout.log"
$Stderr = Join-Path $OutputDir "stderr.log"
$WatchLog = Join-Path $OutputDir "shadow-watch.log"
$StopFile = Join-Path $OutputDir "shadow-watch.stop"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python virtual environment not found: $Python"
}
if (-not (Test-Path -LiteralPath $Manifest)) {
    throw "Frozen manifest not found: $Manifest"
}
$Candidate = "OPENING_STATE_QUEUE_TARGET_GRID_V1"
try {
    $Candidate = (Get-Content -LiteralPath $Manifest -Raw | ConvertFrom-Json).candidate
} catch {
    throw "Could not read frozen manifest candidate: $($_.Exception.Message)"
}
if ($PollSeconds -lt 60) {
    throw "PollSeconds must be at least 60 for read-only shadow watching."
}
if ($MaxCycles -lt 1) {
    throw "MaxCycles must be positive."
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$WorkerScript = @"
`$ErrorActionPreference = "Continue"
Set-Location -LiteralPath "$Root"
`$Python = "$Python"
`$Manifest = "$Manifest"
`$OutputDir = "$OutputDir"
`$Report = "$Report"
`$Heartbeat = "$Heartbeat"
`$Stdout = "$Stdout"
`$Stderr = "$Stderr"
`$WatchLog = "$WatchLog"
`$StopFile = "$StopFile"
`$ProspectiveStart = "$ProspectiveStart"
`$PollSeconds = $PollSeconds
`$MaxCycles = $MaxCycles
New-Item -ItemType Directory -Force -Path `$OutputDir | Out-Null
for (`$Cycle = 1; `$Cycle -le `$MaxCycles; `$Cycle++) {
    if (Test-Path -LiteralPath `$StopFile) {
        Add-Content -LiteralPath `$WatchLog -Value (([DateTimeOffset]::UtcNow.ToString("o")) + " STOP_FILE cycle=" + `$Cycle)
        break
    }
    `$Started = [DateTimeOffset]::UtcNow.ToString("o")
    Add-Content -LiteralPath `$WatchLog -Value (`$Started + " START cycle=" + `$Cycle)
    & `$Python -m cli.main one-minute-opening-target-grid-shadow-step --manifest `$Manifest --prospective-start `$ProspectiveStart --output `$Report 1> `$Stdout 2> `$Stderr
    `$Code = `$LASTEXITCODE
    `$Ended = [DateTimeOffset]::UtcNow.ToString("o")
    `$Summary = `$Ended + " END cycle=" + `$Cycle + " exit=" + `$Code
    if (Test-Path -LiteralPath `$Report) {
        try {
            `$Result = Get-Content -LiteralPath `$Report -Raw | ConvertFrom-Json
            `$Summary += " decision=" + `$Result.decision + " fills=" + `$Result.metrics.fills + " sessions=" + `$Result.candidate_session_count + " pf=" + `$Result.metrics.profit_factor + " net=" + `$Result.metrics.net_profit
            if (`$Result.decision -eq "PASS_PROSPECTIVE_SHADOW" -or `$Result.decision -eq "FAIL_PROSPECTIVE_SHADOW") {
                Add-Content -LiteralPath `$WatchLog -Value `$Summary
                break
            }
            if (`$Result.decision -ne "COLLECTING_PROSPECTIVE_SHADOW") {
                Add-Content -LiteralPath `$WatchLog -Value (`$Summary + " unexpected_decision")
                break
            }
        } catch {
            `$Summary += " parse_error=" + `$_.Exception.Message
        }
    }
    Add-Content -LiteralPath `$WatchLog -Value `$Summary
    Start-Sleep -Seconds `$PollSeconds
}
"@

if ($Foreground) {
    Invoke-Expression $WorkerScript
    exit $LASTEXITCODE
}

$Encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($WorkerScript))
$Worker = Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", $Encoded) `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -PassThru

[pscustomobject]@{
    process_id = $Worker.Id
    session_name = $SessionName
    candidate = $Candidate
    prospective_start = $ProspectiveStart
    poll_seconds = $PollSeconds
    max_cycles = $MaxCycles
    output_dir = $OutputDir
    report_path = $Report
    heartbeat_path = $Heartbeat
    watch_log = $WatchLog
    stop_file = $StopFile
}
