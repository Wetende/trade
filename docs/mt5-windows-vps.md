# MT5 Account-Ready Execution on Windows and VPS

This runbook is for running TradingAgents with MetaTrader 5 Desktop on a home
Windows computer first, then moving the same setup to a Windows VPS.

If another AI agent is continuing this on the Windows machine, start with
[Windows AI Agent Handoff](windows-agent-handoff.md).

The code does not assume demo or real accounts. You must set
`TRADINGAGENTS_MT5_ACCOUNT_MODE` to match the account currently logged into MT5.

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

## 3. Configure Account Mode

Use demo, real, or contest exactly as intended:

```bash
TRADINGAGENTS_MT5_ACCOUNT_MODE=demo
TRADINGAGENTS_MT5_EXECUTION_MODE=dry_run
```

For broker order sending:

```bash
TRADINGAGENTS_MT5_EXECUTION_MODE=broker
```

For real-account broker order sending, this acknowledgement is also required:

```bash
TRADINGAGENTS_MT5_ALLOW_REAL_ORDERS=I_UNDERSTAND_REAL_MONEY_IS_AT_RISK
```

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

After a run, inspect the local evidence trail:

```text
<results_dir>\mt5_runner\summary.json
<results_dir>\mt5_runner\cycles.jsonl
<results_dir>\<analysis-symbol>\engine_telemetry\engine_payload_<as-of>.json
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
