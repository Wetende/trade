# One Minute Scalper Machine Migration

This guide reproduces the deterministic One Minute Scalper on a new Windows
machine without copying credentials or generated broker state into Git.

## Supported environment

- Windows 10 or 11
- 64-bit Python 3.10 through 3.13
- Git
- MetaTrader 5 Desktop installed from the broker
- the official `MetaTrader5` Python bridge
- a DEMO account with algorithmic trading enabled

The project metadata is authoritative for Python compatibility:
`requires-python = ">=3.10,<3.14"`. Python 3.13 is the preferred Windows
baseline for the current repository.

## Clone and create the environment

```powershell
git clone https://github.com/toodennis106/trade.git trade
Set-Location trade
git checkout main

.\scripts\setup-windows.ps1
```

`uv.lock` is tracked for reproducibility, but `uv` is optional. If it is
installed:

```powershell
uv sync --group dev
uv pip install MetaTrader5
```

The MT5 bridge is installed separately because it is Windows- and
terminal-specific.

## Expected project layout

```text
trade/
  cli/
  docs/
  tests/
    fixtures/
  tradingagents/
  .env.example
  pyproject.toml
  requirements.txt
  uv.lock
```

The following are created locally and are intentionally not portable:

```text
.env
.venv/
runtime/
results/
reports/mt5_history_reverse_engineering/
```

## Configure MT5 safely

Copy the placeholder template:

```powershell
Copy-Item .env.example .env
```

Populate these names locally. Do not paste their values into documentation,
issues, chat, logs, screenshots, or commits:

```text
TRADINGAGENTS_MT5_LOGIN
TRADINGAGENTS_MT5_PASSWORD
TRADINGAGENTS_MT5_SERVER
TRADINGAGENTS_MT5_EXPECTED_LOGIN
TRADINGAGENTS_MT5_EXPECTED_SERVER
TRADINGAGENTS_MT5_SYMBOL
TRADINGAGENTS_MT5_PATH
```

Use these safe One Minute Scalper settings:

```dotenv
TRADINGAGENTS_REQUIRE_DEMO_ACCOUNT=true
TRADINGAGENTS_MT5_VOLUME=1.0
TRADINGAGENTS_TRADING_MODE=ENTRY_ONLY
TRADINGAGENTS_DECISION_MODE=engine
TRADINGAGENTS_ENTRY_PROFILE_MODE=fast_only
TRADINGAGENTS_FAST_ENTRIES_ENABLED=true
TRADINGAGENTS_TIMEFRAME=1m
TRADINGAGENTS_CONFIRMATION_TIMEFRAME=1m
TRADINGAGENTS_FAST_TIMEFRAME=1m
TRADINGAGENTS_FAST_CONFIRMATION_TIMEFRAME=1m
TRADINGAGENTS_FAST_HISTORY_WINDOW_CANDLES=60
TRADINGAGENTS_FAST_REACTION_PENDING_SECONDS=20
TRADINGAGENTS_FAST_IMPULSE_PENDING_SECONDS=45
TRADINGAGENTS_FAST_VOLUME_BOOST_ENABLED=false
TRADINGAGENTS_RUNNER_POLL_SECONDS=5
TRADINGAGENTS_RUNNER_MAINTENANCE_POLL_SECONDS=1
TRADINGAGENTS_RUNNER_MAX_SESSION_LOSS=600
```

Do not define `TRADINGAGENTS_MT5_ALLOW_REAL_ORDERS`. The One Minute Scalper
runner covered by this guide is DEMO-only.

Open MT5 Desktop, sign in directly on the new machine, select the configured
symbol, and enable algorithmic trading. Do not copy an MT5 terminal credential
store from the old machine.

## Verify the installation

Run the complete local suite:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Run the focused deterministic and broker suites:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/test_one_minute_entry_model.py `
  tests/test_one_minute_signal_replay.py `
  tests/test_mt5_broker.py `
  tests/test_mt5_execution.py `
  tests/test_execution_journal.py `
  tests/test_execution_state.py `
  tests/test_cli_mt5_execution.py
```

Probe the broker connection without placing an order. The command returns only
sanitized operator status; account login, server, account holder, balance,
equity, company, and terminal path are excluded:

```powershell
.\.venv\Scripts\python.exe -m cli.main broker-probe --json-only
```

Before starting a worker, verify all of the following:

- account safety reports DEMO and passes
- trading permission is enabled
- tick and closed M1 data are fresh
- the configured symbol is available
- there are zero open orders
- there are zero open positions

If an order or position exists, do not start a replacement worker and do not
close it automatically.

## Create a fresh results session

Create a new timestamped directory for every run:

```powershell
$stamp = Get-Date -Format 'yyyy-MM-dd-HHmmss'
$session = Join-Path (Resolve-Path '.').Path "results\$stamp-one-minute-scalper"
New-Item -ItemType Directory -Force -Path $session | Out-Null
$env:TRADINGAGENTS_RESULTS_DIR = $session
```

Never reuse a prior session directory. The stable execution-state directory is
local runtime data and remains separate from telemetry:

```dotenv
TRADINGAGENTS_MT5_EXECUTION_STATE_DIR=runtime/mt5_execution_state
```

Its per-account directory uses a one-way hashed namespace. Raw login and
server values do not appear in paths. Consumed M1 opening evidence is durable
there so a fresh telemetry session cannot immediately resubmit the same stale
local opening. Completed position excursion and execution-timeline records are
also retained locally for reconciliation.

## Start one hidden DEMO worker

Use the tracked launcher:

```powershell
.\scripts\start-one-minute-demo.ps1
```

The launcher refuses duplicate workers and refuses to start unless the
sanitized preflight reports a connected DEMO account, enabled trading, a
fresh tick, zero open orders, and zero open positions. It pins the canonical
M1 profile in process environment, creates a fresh timestamped results
directory, and starts exactly one hidden worker.

Impulse confirmations have two additional deterministic closed-M1 guards:

```text
IMPULSE_TWO_SIDED_STRUCTURE
WEAK_IMPULSE_BODY
```

The first rejects an impulse when the latest closed candle simultaneously
breaks repeated high and low zones. The second requires the impulse body to be
at least `0.50` of the preceding 12 closed candles' median range. These guards
do not apply to respect or fakeout confirmations. Pressure and active pulse
remain context rather than global vetoes.

Do not force a trade. The runner must wait for a valid closed-M1 opening.

Verify that exactly one worker exists, the heartbeat advances, stderr remains
empty, and:

```text
account_safety.require_demo = true
account_safety.trade_mode = DEMO
account_safety.passed = true
trading_mode = ENTRY_ONLY
data_status.reference_source = mt5_tick
data_status.healthy = true
runner health agrees with engine health
open orders = 0
open positions = 0
```

## Files that must be transferred separately

Only the populated `.env` values need secure re-entry or transfer through an
approved secret manager. API keys are unnecessary for `--decision-mode
engine`, but any used by other commands remain secrets.

Do not transfer through Git:

- broker passwords, account identifiers, or server credentials
- populated `.env` files
- MT5 terminal credential stores
- `runtime/` durable state from another account or machine
- raw `results/` telemetry
- raw broker history exports
- screenshots containing account or balance metadata

The tracked sanitized forensic report and deterministic fixtures are sufficient
to reproduce the code-level analysis. Generated session files are excluded
because they contain machine paths, order/deal identifiers, account metadata,
and large redundant telemetry streams.
