[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$EnvFile = Join-Path $Root ".env"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Missing .venv. Run scripts/setup-windows.ps1 first."
}
if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Missing local .env. Copy .env.example and populate it securely."
}

$existingWorkers = @(
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -match "^python(w)?\.exe$" -and
            $_.CommandLine -match "cli\.main\s+mt5-run"
        }
)
if ($existingWorkers.Count -ne 0) {
    throw "An MT5 runner process is already active. Refusing to start a duplicate."
}

# These process-level values override .env and pin the canonical DEMO profile.
$env:TRADINGAGENTS_REQUIRE_DEMO_ACCOUNT = "true"
$env:TRADINGAGENTS_MT5_ALLOW_REAL_ORDERS = "false"
$env:TRADINGAGENTS_MT5_VOLUME = "1.0"
$env:TRADINGAGENTS_TRADING_MODE = "ENTRY_ONLY"
$env:TRADINGAGENTS_DECISION_MODE = "engine"
$env:TRADINGAGENTS_ENTRY_PROFILE_MODE = "fast_only"
$env:TRADINGAGENTS_FAST_ENTRIES_ENABLED = "true"
$env:TRADINGAGENTS_TIMEFRAME = "1m"
$env:TRADINGAGENTS_CONFIRMATION_TIMEFRAME = "1m"
$env:TRADINGAGENTS_FAST_TIMEFRAME = "1m"
$env:TRADINGAGENTS_FAST_CONFIRMATION_TIMEFRAME = "1m"
$env:TRADINGAGENTS_FAST_HISTORY_WINDOW_CANDLES = "60"
$env:TRADINGAGENTS_FAST_REACTION_PENDING_SECONDS = "20"
$env:TRADINGAGENTS_FAST_IMPULSE_PENDING_SECONDS = "45"
$env:TRADINGAGENTS_FAST_VOLUME_BOOST_ENABLED = "false"
$env:TRADINGAGENTS_RUNNER_POLL_SECONDS = "5"
$env:TRADINGAGENTS_RUNNER_MAINTENANCE_POLL_SECONDS = "1"
$env:TRADINGAGENTS_RUNNER_MAX_SESSION_LOSS = "600"

$probeLines = & $Python -m cli.main broker-probe --json-only
if ($LASTEXITCODE -ne 0) {
    throw "The read-only MT5 safety probe failed."
}
$probe = ($probeLines -join [Environment]::NewLine) | ConvertFrom-Json
if (-not $probe.connected) {
    throw "MT5 is not connected."
}
if (-not $probe.account_safety.passed) {
    throw "MT5 account safety failed."
}
if ($probe.account_safety.trade_mode -ne "DEMO") {
    throw "The One Minute Scalper requires a DEMO account."
}
if ($probe.open_order_count -ne 0) {
    throw "Open broker orders exist. Refusing to start a replacement worker."
}
if ($probe.open_position_count -ne 0) {
    throw "Open broker positions exist. Refusing to start a replacement worker."
}
if (-not $probe.symbol.trade_allowed) {
    throw "MT5 algorithmic trading permission is disabled."
}
if ($probe.symbol.tradeapi_disabled) {
    throw "The MT5 trading API is disabled."
}
if (-not $probe.symbol.tick_time_utc) {
    throw "The MT5 tick timestamp is unavailable."
}
$tickTime = [DateTimeOffset]::Parse($probe.symbol.tick_time_utc).ToUniversalTime()
$tickAge = ([DateTimeOffset]::UtcNow - $tickTime).TotalSeconds
if ($tickAge -lt -5 -or $tickAge -gt 120) {
    throw "The MT5 tick is stale or future-dated."
}

$stamp = Get-Date -Format "yyyy-MM-dd-HHmmss"
$Session = Join-Path $Root "results\$stamp-one-minute-scalper-evidence"
New-Item -ItemType Directory -Force -Path $Session | Out-Null
$env:TRADINGAGENTS_RESULTS_DIR = $Session

$stdout = Join-Path $Session "runner.stdout.log"
$stderr = Join-Path $Session "runner.stderr.log"
$worker = Start-Process `
    -FilePath $Python `
    -ArgumentList "-m","cli.main","mt5-run","--poll-seconds","5","--decision-mode","engine" `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -WindowStyle Hidden `
    -PassThru

Start-Sleep -Seconds 2
if ($worker.HasExited) {
    throw "The DEMO worker exited during startup. Inspect the session stderr log."
}

[ordered]@{
    session = $Session
    pid = $worker.Id
    demo_safety = $probe.account_safety.passed
    trade_mode = $probe.account_safety.trade_mode
    open_order_count = $probe.open_order_count
    open_position_count = $probe.open_position_count
    active = $true
} | ConvertTo-Json
