[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Root,
    [Parameter(Mandatory = $true)]
    [string]$Python,
    [Parameter(Mandatory = $true)]
    [string]$Launcher,
    [Parameter(Mandatory = $true)]
    [string]$ExperimentalDemoRecord,
    [Parameter(Mandatory = $true)]
    [string]$RuntimeDir,
    [Parameter(Mandatory = $true)]
    [string]$DeadlineUtc,
    [int]$PollSeconds = 30
)

$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $Root
$Heartbeat = Join-Path $RuntimeDir "heartbeat.json"
$Checkpoints = Join-Path $RuntimeDir "checkpoints.jsonl"
$Log = Join-Path $RuntimeDir "supervisor.log"
$PidFile = Join-Path $RuntimeDir "supervisor.pid"
$StopFile = Join-Path $RuntimeDir "supervisor.stop"
$LearningManifest = Join-Path $RuntimeDir "learning-sources.json"
$LearningLedger = Join-Path $RuntimeDir "learning-ledger.json"
$LearningHeartbeat = Join-Path $RuntimeDir "learning-heartbeat.json"
$BaseLearningManifest = Join-Path $Root (
    "docs\analysis\2026-07-15-one-minute-learning-sources.json"
)
$Deadline = [DateTimeOffset]::Parse($DeadlineUtc).ToUniversalTime()
$LastCheckpointSession = $null
$ConsecutiveLaunchFailures = 0
$LastLaunchHealthHold = $null
$LastLearningUpdate = $null

function Write-AtomicJson {
    param(
        [string]$Path,
        [object]$Payload
    )
    $Temporary = $Path + ".tmp"
    $Payload | ConvertTo-Json -Depth 12 |
        Set-Content -LiteralPath $Temporary -Encoding UTF8
    Move-Item -LiteralPath $Temporary -Destination $Path -Force
}

function Write-AtomicUtf8Json {
    param(
        [string]$Path,
        [object]$Payload
    )
    $Temporary = $Path + ".tmp"
    $Json = $Payload | ConvertTo-Json -Depth 20
    $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Temporary, $Json, $Utf8NoBom)
    Move-Item -LiteralPath $Temporary -Destination $Path -Force
}

function Get-RunnerProcesses {
    return @(
        Get-CimInstance Win32_Process |
            Where-Object {
                $_.Name -match "^python(w)?\.exe$" -and
                $_.CommandLine -match "cli\.main\s+mt5-run" -and
                $_.CommandLine -match "experimental-demo-record"
            }
    )
}

function Get-LatestSession {
    return Get-ChildItem -LiteralPath (Join-Path $Root "results") -Directory |
        Where-Object {
            $_.Name -like "*-one-minute-experimental-learning-vol01"
        } |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
}

function Read-RunnerHeartbeat {
    param([System.IO.DirectoryInfo]$Session)
    if ($null -eq $Session) {
        return $null
    }
    $Path = Join-Path $Session.FullName "mt5_runner\heartbeat.json"
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    try {
        return (Get-Content -LiteralPath $Path -Raw) | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Read-BrokerProbe {
    $Lines = & $Python -m cli.main broker-probe --json-only 2>&1
    if ($LASTEXITCODE -ne 0) {
        return $null
    }
    try {
        return ($Lines -join [Environment]::NewLine) | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Get-Checkpoint {
    param(
        [System.IO.DirectoryInfo]$Session,
        [object]$Probe
    )
    $SummaryPath = Join-Path $Session.FullName "mt5_runner\summary.json"
    $RunnerStdoutPath = Join-Path $Session.FullName "runner.stdout.log"
    $RunnerStderrPath = Join-Path $Session.FullName "runner.stderr.log"
    $Summary = $null
    if (Test-Path -LiteralPath $SummaryPath) {
        try {
            $Summary = (
                Get-Content -LiteralPath $SummaryPath -Raw
            ) | ConvertFrom-Json
        } catch {
            $Summary = $null
        }
    }
    $TradeHistory = if ($null -ne $Summary) {
        $Summary.trade_history
    } else {
        $null
    }
    $RunnerExit = $null
    if (Test-Path -LiteralPath $RunnerStdoutPath) {
        try {
            $RunnerStdout = (
                Get-Content -LiteralPath $RunnerStdoutPath -Raw
            ).Trim()
            if ($RunnerStdout) {
                $RunnerExit = $RunnerStdout | ConvertFrom-Json
            }
        } catch {
            $RunnerExit = $null
        }
    }
    $RunnerStderrTail = @()
    if (Test-Path -LiteralPath $RunnerStderrPath) {
        $RunnerStderrTail = @(
            Get-Content -LiteralPath $RunnerStderrPath -Tail 20 |
                Where-Object { $_.Trim() }
        )
    }
    $StartedAt = $null
    $UpdatedAt = $null
    if ($null -ne $Summary) {
        try {
            $StartedAt = [DateTimeOffset]::Parse(
                [string]$Summary.started_at_utc
            ).ToUniversalTime()
        } catch {
            $StartedAt = $null
        }
        try {
            $UpdatedAt = [DateTimeOffset]::Parse(
                [string]$Summary.updated_at_utc
            ).ToUniversalTime()
        } catch {
            $UpdatedAt = $null
        }
    }
    $ObservedDurationSeconds = if (
        $null -ne $StartedAt -and $null -ne $UpdatedAt
    ) {
        [Math]::Max(0.0, ($UpdatedAt - $StartedAt).TotalSeconds)
    } else {
        $null
    }
    $ExitStatus = if ($null -ne $RunnerExit) {
        [string]$RunnerExit.status
    } else {
        $null
    }
    $CompletedDrain = (
        $ExitStatus -like "STOPPED_*_DRAINED_FLAT" -and
        $RunnerStderrTail.Count -eq 0
    )
    $CompletionStatus = if ($CompletedDrain) {
        "COMPLETED_DRAINED_FLAT"
    } elseif ($RunnerStderrTail.Count -gt 0) {
        "INCOMPLETE_RUNNER_ERROR"
    } elseif ($null -eq $RunnerExit) {
        "INCOMPLETE_MISSING_EXIT_RESULT"
    } else {
        "INCOMPLETE_UNVERIFIED_EXIT"
    }
    $Closed = if ($null -ne $TradeHistory) {
        [int]$TradeHistory.closed_trade_count
    } else {
        0
    }
    $GrossProfit = if ($null -ne $TradeHistory) {
        [double]$TradeHistory.gross_profit
    } else {
        0.0
    }
    $GrossLoss = if ($null -ne $TradeHistory) {
        [double]$TradeHistory.gross_loss
    } else {
        0.0
    }
    $NetProfit = if ($null -ne $TradeHistory) {
        [double]$TradeHistory.net_profit
    } else {
        0.0
    }
    $ProfitFactor = if ([Math]::Abs($GrossLoss) -gt 0.000000000001) {
        $GrossProfit / [Math]::Abs($GrossLoss)
    } elseif ($GrossProfit -gt 0) {
        "INF"
    } else {
        $null
    }
    $Expectancy = if ($Closed -gt 0) {
        $NetProfit / $Closed
    } else {
        $null
    }
    $Rejections = @{}
    if ($null -ne $Summary) {
        foreach (
            $Property in $Summary.candidate_rejection_reason_counts.PSObject.Properties
        ) {
            $Rejections[$Property.Name] = [int]$Property.Value
        }
    }
    $TopRejections = @(
        $Rejections.GetEnumerator() |
            Sort-Object Value -Descending |
            Select-Object -First 12 |
            ForEach-Object {
                [ordered]@{
                    reason = $_.Key
                    count = $_.Value
                }
            }
    )
    return [ordered]@{
        schema_version = 1
        checkpoint_utc = [DateTimeOffset]::UtcNow.ToString("o")
        session = $Session.FullName
        evidence_role = "HYPOTHESIS_GENERATION_ONLY"
        completion_status = $CompletionStatus
        completed_learning_source = $CompletedDrain
        session_started_at_utc = if ($null -ne $StartedAt) {
            $StartedAt.ToString("o")
        } else {
            $null
        }
        session_updated_at_utc = if ($null -ne $UpdatedAt) {
            $UpdatedAt.ToString("o")
        } else {
            $null
        }
        observed_duration_seconds = $ObservedDurationSeconds
        runner_exit_status = $ExitStatus
        runner_exit_result = $RunnerExit
        runner_stderr_tail = $RunnerStderrTail
        strategy_mutation_enabled = $false
        automatic_promotion_enabled = $false
        account_safety = $Probe.account_safety
        open_order_count = [int]$Probe.open_order_count
        open_position_count = [int]$Probe.open_position_count
        orders_placed = if ($null -ne $Summary) {
            [int]$Summary.orders_placed
        } else {
            0
        }
        orders_rejected = if ($null -ne $Summary) {
            [int]$Summary.orders_rejected
        } else {
            0
        }
        orders_skipped = if ($null -ne $Summary) {
            [int]$Summary.orders_skipped
        } else {
            0
        }
        broker_rejections = if ($null -ne $Summary) {
            [int]$Summary.broker_rejections
        } else {
            0
        }
        filled_trades = if ($null -ne $TradeHistory) {
            [int]$TradeHistory.filled_trade_count
        } else {
            0
        }
        closed_trades = $Closed
        wins = if ($null -ne $TradeHistory) {
            [int]$TradeHistory.wins
        } else {
            0
        }
        losses = if ($null -ne $TradeHistory) {
            [int]$TradeHistory.losses
        } else {
            0
        }
        break_even = if ($null -ne $TradeHistory) {
            [int]$TradeHistory.break_even
        } else {
            0
        }
        net_profit = $NetProfit
        gross_profit = $GrossProfit
        gross_loss = $GrossLoss
        profit_factor = $ProfitFactor
        expectancy = $Expectancy
        unhealthy_data_checks = if ($null -ne $Summary) {
            [int]$Summary.data_health.unhealthy_checks
        } else {
            0
        }
        execution_skip_counts = if ($null -ne $Summary) {
            $Summary.execution_skip_counts
        } else {
            @{}
        }
        top_candidate_rejections = $TopRejections
        summary_path = $SummaryPath
    }
}

function Update-ControlledLearning {
    param(
        [System.IO.DirectoryInfo]$Session,
        [object]$Checkpoint
    )
    $Now = [DateTimeOffset]::UtcNow.ToString("o")
    if (-not $Checkpoint.completed_learning_source) {
        $Result = [ordered]@{
            status = "SKIPPED_INCOMPLETE_SESSION"
            updated_at_utc = $Now
            session = $Session.FullName
            broker_mutation_enabled = $false
            live_rule_mutation_enabled = $false
            automatic_promotion_enabled = $false
        }
        Write-AtomicJson -Path $LearningHeartbeat -Payload $Result
        Add-Content -LiteralPath $Log -Value (
            $Now + " LEARNING_SKIPPED_INCOMPLETE session=" + $Session.Name
        )
        return $Result
    }
    try {
        $ManifestSource = if (Test-Path -LiteralPath $LearningManifest) {
            $LearningManifest
        } else {
            $BaseLearningManifest
        }
        if (-not (Test-Path -LiteralPath $ManifestSource)) {
            throw "Controlled-learning base manifest is missing: $ManifestSource"
        }
        $Manifest = (
            Get-Content -LiteralPath $ManifestSource -Raw
        ) | ConvertFrom-Json
        if (
            $Manifest.schema_version -ne 1 -or
            $Manifest.strategy_scope -ne "one_minute_scalper" -or
            $Manifest.source_role -ne "HYPOTHESIS_GENERATION_ONLY"
        ) {
            throw "Controlled-learning source manifest guardrail failed."
        }
        if (
            $Manifest.guardrails.broker_mutation_enabled -or
            $Manifest.guardrails.live_rule_mutation_enabled -or
            $Manifest.guardrails.automatic_promotion_enabled
        ) {
            throw "Controlled-learning source manifest grants prohibited permissions."
        }
        $Sessions = @($Manifest.sessions)
        if ($Sessions -notcontains $Session.FullName) {
            $Sessions += $Session.FullName
        }
        $Manifest.sessions = @($Sessions | Select-Object -Unique)
        Write-AtomicUtf8Json -Path $LearningManifest -Payload $Manifest

        $Lines = & $Python -m cli.main one-minute-learn `
            --source-manifest $LearningManifest `
            --output $LearningLedger 2>&1
        $Code = $LASTEXITCODE
        if ($Code -ne 0 -or -not (Test-Path -LiteralPath $LearningLedger)) {
            throw (
                "Controlled-learning command failed with exit code " +
                $Code + ": " + ($Lines -join [Environment]::NewLine)
            )
        }
        $Ledger = (
            Get-Content -LiteralPath $LearningLedger -Raw
        ) | ConvertFrom-Json
        if (
            $Ledger.broker_mutation_enabled -or
            $Ledger.live_rule_mutation_enabled -or
            $Ledger.automatic_promotion_enabled -or
            $Ledger.operational_permissions.place_or_modify_orders -or
            $Ledger.operational_permissions.change_strategy_configuration -or
            $Ledger.operational_permissions.create_promotion_record -or
            $Ledger.operational_permissions.authorize_demo_start -or
            $Ledger.operational_permissions.authorize_real_start
        ) {
            throw "Controlled-learning ledger guardrail failed."
        }
        $Result = [ordered]@{
            status = "UPDATED_RESEARCH_LEDGER"
            updated_at_utc = $Now
            session = $Session.FullName
            source_manifest = $LearningManifest
            ledger_path = $LearningLedger
            ledger_sha256 = (
                Get-FileHash -Algorithm SHA256 -LiteralPath $LearningLedger
            ).Hash.ToLowerInvariant()
            source_session_count = @($Ledger.source_registry.sessions).Count
            summary = $Ledger.diagnostics.summary
            hypothesis_generation_cutoff_utc = (
                $Ledger.candidate_incubation.evidence_isolation.
                    hypothesis_generation_cutoff_utc
            )
            broker_mutation_enabled = $false
            live_rule_mutation_enabled = $false
            automatic_promotion_enabled = $false
        }
        Write-AtomicJson -Path $LearningHeartbeat -Payload $Result
        Add-Content -LiteralPath $Log -Value (
            $Now + " LEARNING_UPDATED session=" + $Session.Name +
            " sources=" + $Result.source_session_count +
            " ledger_sha256=" + $Result.ledger_sha256
        )
        return $Result
    } catch {
        $Failure = [ordered]@{
            status = "LEARNING_UPDATE_FAILED"
            updated_at_utc = $Now
            session = $Session.FullName
            reason = $_.Exception.Message
            source_manifest = $LearningManifest
            ledger_path = $LearningLedger
            broker_mutation_enabled = $false
            live_rule_mutation_enabled = $false
            automatic_promotion_enabled = $false
        }
        Write-AtomicJson -Path $LearningHeartbeat -Payload $Failure
        Add-Content -LiteralPath $Log -Value (
            $Now + " LEARNING_UPDATE_FAILED session=" + $Session.Name +
            " reason=" + $Failure.reason
        )
        return $Failure
    }
}

function Start-NextRunner {
    param([double]$DurationHours)
    $DurationText = $DurationHours.ToString(
        [Globalization.CultureInfo]::InvariantCulture
    )
    $Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $LauncherStdout = Join-Path $RuntimeDir "launcher-$Stamp.stdout.log"
    $LauncherStderr = Join-Path $RuntimeDir "launcher-$Stamp.stderr.log"
    $Process = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @(
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            $Launcher,
            "-ExperimentalDemoRecord",
            $ExperimentalDemoRecord,
            "-Volume",
            "0.1",
            "-DurationHours",
            $DurationText,
            "-MaxSessionLoss",
            "20",
            "-ShutdownGraceSeconds",
            "120"
        ) `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $LauncherStdout `
        -RedirectStandardError $LauncherStderr `
        -WindowStyle Hidden `
        -PassThru
    return [pscustomobject]@{
        Process = $Process
        StdoutPath = $LauncherStdout
        StderrPath = $LauncherStderr
    }
}

function Get-LaunchHealthHoldReason {
    param([object]$Launch)
    if (
        $null -eq $Launch -or
        $null -eq $Launch.Process -or
        -not $Launch.Process.HasExited -or
        -not (Test-Path -LiteralPath $Launch.StderrPath)
    ) {
        return $null
    }
    try {
        $Stderr = Get-Content -LiteralPath $Launch.StderrPath -Raw
        if ($Stderr -match "MT5 tick is stale or future-dated") {
            return "MT5_TICK_STALE_OR_FUTURE_DATED"
        }
    } catch {
        return $null
    }
    return $null
}

try {
    while ([DateTimeOffset]::UtcNow -lt $Deadline) {
        if (Test-Path -LiteralPath $StopFile) {
            Add-Content -LiteralPath $Log -Value (
                [DateTimeOffset]::UtcNow.ToString("o") + " STOP_FILE"
            )
            break
        }

        $Runners = @(Get-RunnerProcesses)
        $Session = Get-LatestSession
        $Probe = $null
        $RunnerHeartbeat = $null
        if ($Runners.Count -gt 0) {
            $RunnerHeartbeat = Read-RunnerHeartbeat -Session $Session
        } else {
            $Probe = Read-BrokerProbe
        }
        $RunnerHeartbeatAgeSeconds = $null
        $RunnerHeartbeatFresh = $false
        if ($null -ne $RunnerHeartbeat) {
            try {
                $RunnerHeartbeatObserved = [DateTimeOffset]::Parse(
                    [string]$RunnerHeartbeat.heartbeat_utc
                ).ToUniversalTime()
                $RunnerHeartbeatAgeSeconds = [Math]::Max(
                    0.0,
                    (
                        [DateTimeOffset]::UtcNow - $RunnerHeartbeatObserved
                    ).TotalSeconds
                )
                $RunnerHeartbeatFresh = $RunnerHeartbeatAgeSeconds -le 120
            } catch {
                $RunnerHeartbeatAgeSeconds = $null
                $RunnerHeartbeatFresh = $false
            }
        }

        $SafetyPassed = (
            $null -ne $Probe -and
            $Probe.connected -and
            $Probe.account_safety.passed -and
            $Probe.account_safety.trade_mode -eq "DEMO"
        )
        $Flat = (
            $SafetyPassed -and
            [int]$Probe.open_order_count -eq 0 -and
            [int]$Probe.open_position_count -eq 0
        )

        if (
            $Runners.Count -eq 0 -and
            $null -ne $Session -and
            $Session.FullName -ne $LastCheckpointSession
        ) {
            if (-not $SafetyPassed) {
                throw "Broker safety proof failed after session exit."
            }
            if (-not $Flat) {
                throw "Session exited without verified-flat DEMO state."
            }
            $Checkpoint = Get-Checkpoint -Session $Session -Probe $Probe
            $LastLearningUpdate = Update-ControlledLearning `
                -Session $Session `
                -Checkpoint $Checkpoint
            $Checkpoint["learning_update"] = $LastLearningUpdate
            Add-Content -LiteralPath $Checkpoints -Value (
                $Checkpoint | ConvertTo-Json -Depth 12 -Compress
            )
            $LastCheckpointSession = $Session.FullName
            Add-Content -LiteralPath $Log -Value (
                [DateTimeOffset]::UtcNow.ToString("o") +
                " CHECKPOINT session=" + $Session.Name +
                " closed=" + $Checkpoint.closed_trades +
                " net=" + $Checkpoint.net_profit
            )
        }

        $RemainingHours = (
            $Deadline - [DateTimeOffset]::UtcNow
        ).TotalHours
        if ($Runners.Count -eq 0 -and $RemainingHours -gt 0.02) {
            if (-not $Flat) {
                throw "Refusing restart without DEMO and zero broker exposure."
            }
            $Launch = Start-NextRunner -DurationHours (
                [Math]::Min(3.0, $RemainingHours)
            )
            $RunnerReady = $false
            for ($Attempt = 1; $Attempt -le 25; $Attempt++) {
                Start-Sleep -Seconds 1
                $Runners = @(Get-RunnerProcesses)
                if ($Runners.Count -gt 0) {
                    $RunnerReady = $true
                    break
                }
                if (
                    $Launch.Process.HasExited -and
                    $Launch.Process.ExitCode -ne 0
                ) {
                    break
                }
            }
            if (-not $RunnerReady) {
                $LaunchHealthHold = Get-LaunchHealthHoldReason -Launch $Launch
                if ($null -ne $LaunchHealthHold) {
                    $ConsecutiveLaunchFailures = 0
                    $LastLaunchHealthHold = $LaunchHealthHold
                    Add-Content -LiteralPath $Log -Value (
                        [DateTimeOffset]::UtcNow.ToString("o") +
                        " LAUNCH_HEALTH_HOLD reason=" + $LaunchHealthHold
                    )
                } else {
                    $ConsecutiveLaunchFailures++
                    Add-Content -LiteralPath $Log -Value (
                        [DateTimeOffset]::UtcNow.ToString("o") +
                        " LAUNCH_FAILURE count=" + $ConsecutiveLaunchFailures
                    )
                    if ($ConsecutiveLaunchFailures -ge 3) {
                        throw "Experimental runner restart failed three times."
                    }
                }
            } else {
                $ConsecutiveLaunchFailures = 0
                $LastLaunchHealthHold = $null
                $Session = Get-LatestSession
                $RunnerHeartbeat = Read-RunnerHeartbeat -Session $Session
                Add-Content -LiteralPath $Log -Value (
                    [DateTimeOffset]::UtcNow.ToString("o") +
                    " RUNNER_STARTED"
                )
            }
        }

        $HeartbeatPayload = [ordered]@{
            schema_version = 1
            heartbeat_utc = [DateTimeOffset]::UtcNow.ToString("o")
            deadline_utc = $Deadline.ToString("o")
            active = $true
            runner_process_count = $Runners.Count
            runner_session = if ($null -ne $Session) {
                $Session.FullName
            } else {
                $null
            }
            runner_heartbeat_utc = if ($null -ne $RunnerHeartbeat) {
                $RunnerHeartbeat.heartbeat_utc
            } else {
                $null
            }
            runner_heartbeat_age_seconds = $RunnerHeartbeatAgeSeconds
            runner_heartbeat_fresh = $RunnerHeartbeatFresh
            account_safety = if ($Runners.Count -gt 0) {
                if ($null -ne $RunnerHeartbeat) {
                    $RunnerHeartbeat.account_safety
                } else {
                    $null
                }
            } elseif ($null -ne $Probe) {
                $Probe.account_safety
            } else {
                $null
            }
            open_order_count = if (
                $Runners.Count -eq 0 -and $null -ne $Probe
            ) {
                [int]$Probe.open_order_count
            } else {
                $null
            }
            open_position_count = if (
                $Runners.Count -eq 0 -and $null -ne $Probe
            ) {
                [int]$Probe.open_position_count
            } else {
                $null
            }
            session_metrics = if ($null -ne $RunnerHeartbeat) {
                [ordered]@{
                    status = $RunnerHeartbeat.status
                    health_gate = $RunnerHeartbeat.health_gate
                    total_checks = $RunnerHeartbeat.summary.total_checks
                    orders_placed = $RunnerHeartbeat.summary.orders_placed
                    orders_rejected = $RunnerHeartbeat.summary.orders_rejected
                    orders_skipped = $RunnerHeartbeat.summary.orders_skipped
                    broker_rejections = $RunnerHeartbeat.summary.broker_rejections
                    filled_trades = (
                        $RunnerHeartbeat.summary.trade_history.filled_trade_count
                    )
                    closed_trades = (
                        $RunnerHeartbeat.summary.trade_history.closed_trade_count
                    )
                    wins = $RunnerHeartbeat.summary.trade_history.wins
                    losses = $RunnerHeartbeat.summary.trade_history.losses
                    break_even = $RunnerHeartbeat.summary.trade_history.break_even
                    net_profit = (
                        $RunnerHeartbeat.summary.trade_history.net_profit
                    )
                    latest_execution = $RunnerHeartbeat.summary.latest_execution
                }
            } else {
                $null
            }
            last_checkpoint_session = $LastCheckpointSession
            last_learning_update = $LastLearningUpdate
            learning_manifest_path = $LearningManifest
            learning_ledger_path = $LearningLedger
            learning_heartbeat_path = $LearningHeartbeat
            consecutive_launch_failures = $ConsecutiveLaunchFailures
            last_launch_health_hold = $LastLaunchHealthHold
            strategy_mutation_enabled = $false
            automatic_promotion_enabled = $false
            volume = 0.1
            max_session_loss = 20.0
        }
        Write-AtomicJson -Path $Heartbeat -Payload $HeartbeatPayload
        Start-Sleep -Seconds $PollSeconds
    }
} catch {
    $Failure = [ordered]@{
        schema_version = 1
        heartbeat_utc = [DateTimeOffset]::UtcNow.ToString("o")
        deadline_utc = $Deadline.ToString("o")
        active = $false
        failed = $true
        reason = $_.Exception.Message
        strategy_mutation_enabled = $false
        automatic_promotion_enabled = $false
    }
    Write-AtomicJson -Path $Heartbeat -Payload $Failure
    Add-Content -LiteralPath $Log -Value (
        [DateTimeOffset]::UtcNow.ToString("o") +
        " FAILURE " + $_.Exception.Message
    )
} finally {
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}
