[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ExperimentalDemoRecord,
    [double]$Volume = 0.1,
    [double]$DurationHours = 3.0,
    [double]$MaxSessionLoss = 20.0,
    [int]$ShutdownGraceSeconds = 120
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$EnvFile = Join-Path $Root ".env"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Missing .venv. Run scripts/setup-windows.ps1 first."
}
if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Missing local .env. Copy .env.example and populate it securely."
}
$ExperimentalDemoRecord = (
    Resolve-Path -LiteralPath $ExperimentalDemoRecord
).Path
if ([Math]::Abs($Volume - 0.1) -gt 0.000000000001) {
    throw "The experimental DEMO volume is frozen at 0.1."
}
if ($DurationHours -le 0 -or $DurationHours -gt 3.0) {
    throw "Each experimental DEMO session must be positive and no longer than 3 hours."
}
if ([Math]::Abs($MaxSessionLoss - 20.0) -gt 0.000000000001) {
    throw "The experimental DEMO session-loss limit is frozen at 20 account-currency units."
}
if ($ShutdownGraceSeconds -ne 120) {
    throw "The experimental DEMO shutdown grace is frozen at 120 seconds."
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

$env:TRADINGAGENTS_REQUIRE_DEMO_ACCOUNT = "true"
$env:TRADINGAGENTS_MT5_ALLOW_REAL_ORDERS = "false"
$env:TRADINGAGENTS_MT5_VOLUME = "0.1"
$env:TRADINGAGENTS_TRADING_MODE = "ENTRY_ONLY"
$env:TRADINGAGENTS_DECISION_MODE = "engine"
$env:TRADINGAGENTS_ENTRY_PROFILE_MODE = "fast_only"
$env:TRADINGAGENTS_FAST_ENTRIES_ENABLED = "true"
$env:TRADINGAGENTS_TIMEFRAME = "1m"
$env:TRADINGAGENTS_CONFIRMATION_TIMEFRAME = "1m"
$env:TRADINGAGENTS_FAST_TIMEFRAME = "1m"
$env:TRADINGAGENTS_FAST_CONFIRMATION_TIMEFRAME = "1m"
$env:TRADINGAGENTS_FAST_HISTORY_WINDOW_CANDLES = "60"
$env:TRADINGAGENTS_FAST_MIN_CANDIDATE_SCORE = "8"
$env:TRADINGAGENTS_FAST_MIN_STOP_SPREAD_MULTIPLE = "2.2"
$env:TRADINGAGENTS_FAST_VOLUME_BOOST_ENABLED = "false"
$env:TRADINGAGENTS_RUNNER_MAX_SESSION_LOSS = "20"
$env:TRADINGAGENTS_RUNNER_BLOCKED_STRATEGY_RULES = (
    "FAILED_HIGH_BREAK_SELL:*,FAILED_LOW_BREAK_BUY:*"
)
$env:TRADINGAGENTS_RUNNER_POLL_SECONDS = "5"
$env:TRADINGAGENTS_RUNNER_MAINTENANCE_POLL_SECONDS = "1"
$env:TRADINGAGENTS_RUNNER_POST_CLOSE_COOLDOWN_SECONDS = "90"
$env:TRADINGAGENTS_RUNNER_LOSS_COOLDOWN_SECONDS = "600"
$env:TRADINGAGENTS_RUNNER_LOSS_STREAK_COOLDOWN_COUNT = "2"
$env:TRADINGAGENTS_RUNNER_LOSS_STREAK_COOLDOWN_SECONDS = "900"

$probeLines = & $Python -m cli.main broker-probe --json-only
if ($LASTEXITCODE -ne 0) {
    throw "The read-only MT5 safety probe failed."
}
$probe = ($probeLines -join [Environment]::NewLine) | ConvertFrom-Json
if (
    -not $probe.connected -or
    -not $probe.account_safety.passed -or
    $probe.account_safety.trade_mode -ne "DEMO"
) {
    throw "The experimental runner requires a connected, verified DEMO account."
}
if ($probe.open_order_count -ne 0 -or $probe.open_position_count -ne 0) {
    throw "The experimental runner requires zero initial broker exposure."
}
if (-not $probe.symbol.trade_allowed -or $probe.symbol.tradeapi_disabled) {
    throw "MT5 algorithmic trading permission is disabled."
}
if (-not $probe.symbol.tick_time_utc) {
    throw "The MT5 tick timestamp is unavailable."
}
$tickTime = [DateTimeOffset]::Parse(
    $probe.symbol.tick_time_utc
).ToUniversalTime()
$tickAge = ([DateTimeOffset]::UtcNow - $tickTime).TotalSeconds
if ($tickAge -lt -5 -or $tickAge -gt 120) {
    throw "The MT5 tick is stale or future-dated."
}

$stamp = Get-Date -Format "yyyy-MM-dd-HHmmss"
$Session = Join-Path $Root (
    "results\$stamp-one-minute-experimental-learning-vol01"
)
New-Item -ItemType Directory -Force -Path $Session | Out-Null
$env:TRADINGAGENTS_RESULTS_DIR = $Session

$stdout = Join-Path $Session "runner.stdout.log"
$stderr = Join-Path $Session "runner.stderr.log"
$worker = Start-Process `
    -FilePath $Python `
    -ArgumentList "-m","cli.main","mt5-run","--poll-seconds","5","--duration-hours",$DurationHours.ToString([Globalization.CultureInfo]::InvariantCulture),"--decision-mode","engine","--experimental-demo-record",$ExperimentalDemoRecord,"--shutdown-grace-seconds","120" `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -WindowStyle Hidden `
    -PassThru

Start-Sleep -Seconds 3
if ($worker.HasExited) {
    throw "The experimental DEMO worker exited during startup. Inspect the session logs."
}

[ordered]@{
    session = $Session
    pid = $worker.Id
    experiment = "ONE_MINUTE_ENTRY_MODEL_EXPERIMENTAL_V1"
    promotion_eligible = $false
    evidence_role = "HYPOTHESIS_GENERATION_ONLY"
    demo_safety = $probe.account_safety.passed
    trade_mode = $probe.account_safety.trade_mode
    open_order_count = $probe.open_order_count
    open_position_count = $probe.open_position_count
    experimental_demo_record = $ExperimentalDemoRecord
    volume = $Volume
    max_session_loss = $MaxSessionLoss
    loss_streak_cooldown_count = 2
    loss_streak_cooldown_seconds = 900
    duration_hours = $DurationHours
    shutdown_grace_seconds = $ShutdownGraceSeconds
    active = $true
} | ConvertTo-Json
