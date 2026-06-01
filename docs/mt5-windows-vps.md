# MT5 Broker Execution on Windows and VPS

This runbook is for running TradingAgents with MetaTrader 5 Desktop on a home
Windows computer first, then moving the same setup to a Windows VPS.

If another AI agent is continuing this on the Windows machine, start with
[Windows AI Agent Handoff](windows-agent-handoff.md).

Configure one MT5 broker connection. TradingAgents reads the account type from
MT5 at runtime and only asks for a real-money acknowledgement when MT5 reports a
real account.

## 1. Install Prerequisites

- Windows 10/11 or Windows Server VPS
- Python 3.10 through 3.13
- Git
- MetaTrader 5 Desktop from your broker
- An MT5 account logged into the desktop terminal

```powershell
uv sync --group dev
uv pip install MetaTrader5
```

## 2. Pull Main

```powershell
git checkout main
git pull origin main
```

## 3. Configure Broker Connection

```bash
TRADINGAGENTS_MT5_LOGIN=123456789
TRADINGAGENTS_MT5_PASSWORD=your-broker-password
TRADINGAGENTS_MT5_SERVER=YourBroker-Server
TRADINGAGENTS_MT5_EXPECTED_LOGIN=123456789
TRADINGAGENTS_MT5_EXPECTED_SERVER=YourBroker-Server
TRADINGAGENTS_MT5_VOLUME=0.01
TRADINGAGENTS_MT5_DEVIATION=20
TRADINGAGENTS_MT5_MAGIC=150015
```

Optional terminal path:

```bash
TRADINGAGENTS_MT5_PATH="C:\Program Files\MetaTrader 5\terminal64.exe"
```

When MT5 reports a real account, broker order sending also requires:

```bash
TRADINGAGENTS_MT5_ALLOW_REAL_ORDERS=I_UNDERSTAND_REAL_MONEY_IS_AT_RISK
```

Do not add the acknowledgement unless the human operator has explicitly approved
real-money order sending.

## 4. Configure Symbols

For gold, analysis data and broker execution symbols can differ:

```bash
TRADINGAGENTS_ANALYSIS_SYMBOL=GC=F
TRADINGAGENTS_BROKER_SYMBOL=XAUUSD.vx
TRADINGAGENTS_MT5_SYMBOL=XAUUSD.vx
```

## 5. Probe MT5

```powershell
tradingagents broker-probe
```

## 6. Run One Full Cycle

```powershell
tradingagents analyze --non-interactive
tradingagents mt5-execute --proposal "<path-to-order-proposal.json>"
tradingagents mt5-monitor --cancel-stale --manage-stops
```

## 7. Run Unattended

```powershell
tradingagents mt5-run --once
tradingagents mt5-run --poll-seconds 30
```

For a bounded live-market forward test, keep `.env` pointed at the intended MT5
account and use only process-local overrides for network or time-filter
settings:

```powershell
$env:HTTP_PROXY=""
$env:HTTPS_PROXY=""
$env:ALL_PROXY=""
$env:GIT_HTTP_PROXY=""
$env:GIT_HTTPS_PROXY=""
$env:TRADINGAGENTS_TIME_FILTER_MODE="block"
tradingagents mt5-run --poll-seconds 30 --duration-hours 4
```

For short forward-test validation during a normally blocked Sunday/Asian window,
set `TRADINGAGENTS_TIME_FILTER_MODE="allow"` only for that process. For
production observation that records setup evidence but still blocks brokerable
orders, use `TRADINGAGENTS_TIME_FILTER_MODE="observe"`.

Do not start a setup-validation run after the Friday gold close. For
observation, Sunday New York reopen is acceptable. For cleaner strategy
validation, prefer London/New York overlap.

After a run, inspect the local evidence trail:

```text
<results_dir>\mt5_runner\summary.json
<results_dir>\mt5_runner\cycles.jsonl
<results_dir>\<analysis-symbol>\engine_telemetry\engine_payload_<as-of>.json
<results_dir>\<broker-symbol>\execution_journal\mt5_events.jsonl
```

The runner summary shows total checks, HOLD/PROPOSED counts, broker-order
counts, broker rejections, categorized HOLD reasons, and latest data-health
status. The engine telemetry shows the raw Daily/4H/1H/M30/M15 decision context.

If required market data is stale or missing, the bot defaults to HOLD instead of
guessing. This is expected safety behavior; inspect `data_status` before
changing strategy rules.

## 8. Keep It Alive on Windows

Use Task Scheduler with:

- Program: path to `uv` or `python`
- Arguments: `run tradingagents mt5-run --poll-seconds 30`
- Start in: project directory
- Restart on failure enabled
- Run whether user is logged on or not only after verifying MT5 stays connected

## 9. Move to VPS

Install the same project and `.env` on a Windows VPS, log into MT5 Desktop,
run `broker-probe`, run `mt5-run --once`, review summary/telemetry, then run the
long-lived command.
