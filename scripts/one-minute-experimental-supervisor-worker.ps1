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
$Deadline = [DateTimeOffset]::Parse($DeadlineUtc).ToUniversalTime()
$LastCheckpointSession = $null
$ConsecutiveLaunchFailures = 0

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

function Start-NextRunner {
    param([double]$DurationHours)
    $DurationText = $DurationHours.ToString(
        [Globalization.CultureInfo]::InvariantCulture
    )
    $Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $LauncherStdout = Join-Path $RuntimeDir "launcher-$Stamp.stdout.log"
    $LauncherStderr = Join-Path $RuntimeDir "launcher-$Stamp.stderr.log"
    return Start-Process `
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
                if ($Launch.HasExited -and $Launch.ExitCode -ne 0) {
                    break
                }
            }
            if (-not $RunnerReady) {
                $ConsecutiveLaunchFailures++
                Add-Content -LiteralPath $Log -Value (
                    [DateTimeOffset]::UtcNow.ToString("o") +
                    " LAUNCH_FAILURE count=" + $ConsecutiveLaunchFailures
                )
                if ($ConsecutiveLaunchFailures -ge 3) {
                    throw "Experimental runner restart failed three times."
                }
            } else {
                $ConsecutiveLaunchFailures = 0
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
            last_checkpoint_session = $LastCheckpointSession
            consecutive_launch_failures = $ConsecutiveLaunchFailures
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
