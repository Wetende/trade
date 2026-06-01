# MT5 Demo Execution on Windows

Use this checklist on the Windows machine that will run MetaTrader 5 Desktop.
Keep broker credentials only in your local `.env`; never commit them.

## 1. Install Prerequisites

- Windows 10/11
- Python `3.10` through `3.13`
- Git
- MetaTrader 5 Desktop from your broker
- A demo MT5 account logged into the desktop terminal

Install the Python MT5 bridge inside the project environment:

```powershell
python -m pip install MetaTrader5
```

If you use `uv`, install/sync the project first:

```powershell
uv sync --group dev
uv pip install MetaTrader5
```

## 2. Pull Main

```powershell
git clone https://github.com/toodennis106/trade.git trade
cd trade
git checkout main
git pull origin main
```

If the repo already exists:

```powershell
cd path\to\tradingagents
git checkout main
git pull origin main
```

## 3. Configure `.env`

```powershell
Copy-Item .env.example .env
```

Set these values in `.env`:

```bash
TRADINGAGENTS_MT5_LOGIN=123456789
TRADINGAGENTS_MT5_PASSWORD=your-demo-password
TRADINGAGENTS_MT5_SERVER=YourBroker-Demo
TRADINGAGENTS_MT5_SYMBOL=XAUUSD
TRADINGAGENTS_MT5_ACCOUNT_MODE=demo
TRADINGAGENTS_MT5_EXPECTED_LOGIN=123456789
TRADINGAGENTS_MT5_EXPECTED_SERVER=YourBroker-Demo
TRADINGAGENTS_MT5_VOLUME=0.01
TRADINGAGENTS_MT5_DEVIATION=20
TRADINGAGENTS_MT5_MAGIC=150015
```

Optional terminal path:

```bash
TRADINGAGENTS_MT5_PATH="C:\Program Files\MetaTrader 5\terminal64.exe"
```

Optional local output location:

```bash
TRADINGAGENTS_RESULTS_DIR=C:\Users\you\.tradingagents\logs
```

## 4. Prepare MT5 Desktop

1. Open MT5 Desktop.
2. Log into the same demo account used in `.env`.
3. Confirm the server name matches `TRADINGAGENTS_MT5_EXPECTED_SERVER`.
4. Keep the terminal open while running the bot.
5. Enable algo/automated trading in MT5 if your terminal requires it for Python `order_send`.

The code also verifies runtime safety before sending any order:

- account mode must be demo
- login must match `TRADINGAGENTS_MT5_EXPECTED_LOGIN`
- server must match `TRADINGAGENTS_MT5_EXPECTED_SERVER`
- pending order volume must match `TRADINGAGENTS_MT5_VOLUME`

## 5. Run Local Tests

These tests do not place broker orders:

```powershell
uv run --group dev pytest tests/test_mt5_broker.py tests/test_mt5_execution.py tests/test_execution_journal.py tests/test_execution_state.py tests/test_cli_mt5_execution.py -q
```

## 6. Probe Broker Connection

This checks MT5 connectivity and account metadata without placing orders:

```powershell
tradingagents broker-probe
```

Do not continue until this succeeds and shows the expected demo login/server.

## 7. Generate an Order Proposal

Run the analysis flow:

```powershell
tradingagents analyze
```

The CLI prints the generated proposal path. It will look like:

```text
C:\Users\you\.tradingagents\logs\XAUUSD\order_proposals\order_proposal_YYYY_MM_DD_HHMM.json
```

Only `PROPOSED` limit-order proposals can execute. `NO_TRADE` proposals are rejected.

## 8. Execute on Demo

Start with fixed demo volume, normally `0.01`.

```powershell
tradingagents mt5-execute --proposal "C:\Users\you\.tradingagents\logs\XAUUSD\order_proposals\order_proposal_YYYY_MM_DD_HHMM.json"
```

Expected behavior:

- connects to MT5
- confirms the demo account guard
- refuses if an active order or position already exists for the symbol
- builds a pending `BUY_LIMIT` or `SELL_LIMIT`
- places the pending order
- records journal and state files

For a bounded live-market demo runner test, keep `.env` safe with
`TRADINGAGENTS_MT5_EXECUTION_MODE=dry_run` and override only the current
PowerShell process:

```powershell
$env:HTTP_PROXY=""
$env:HTTPS_PROXY=""
$env:ALL_PROXY=""
$env:GIT_HTTP_PROXY=""
$env:GIT_HTTPS_PROXY=""
$env:TRADINGAGENTS_MT5_ACCOUNT_MODE="demo"
$env:TRADINGAGENTS_MT5_EXECUTION_MODE="broker"
$env:TRADINGAGENTS_TIME_FILTER_MODE="block"
tradingagents mt5-run --poll-seconds 30 --duration-hours 4
```

For short demo validation during a normally blocked Sunday/Asian window, set
`TRADINGAGENTS_TIME_FILTER_MODE="allow"` only for that process. For production
observation that records setup evidence but still blocks brokerable orders, use
`TRADINGAGENTS_TIME_FILTER_MODE="observe"`.

Do not start a setup-validation run after the Friday gold close. For
observation, Sunday New York reopen is acceptable. For cleaner strategy
validation, prefer London/New York overlap.

## 9. Monitor and Manage

Read-only snapshot:

```powershell
tradingagents mt5-monitor
```

Cancel stale pending orders after the activation window:

```powershell
tradingagents mt5-monitor --cancel-stale
```

Move stops to break-even when the open position qualifies:

```powershell
tradingagents mt5-monitor --manage-stops
```

You can run both lifecycle actions together:

```powershell
tradingagents mt5-monitor --cancel-stale --manage-stops
```

## 10. Check Audit Files

Execution events:

```text
<results_dir>\XAUUSD\execution_journal\mt5_events.jsonl
```

Active pending-order state:

```text
<results_dir>\XAUUSD\execution_state\mt5_state.json
```

Runner summary and raw engine telemetry:

```text
<results_dir>\mt5_runner\summary.json
<results_dir>\mt5_runner\cycles.jsonl
<results_dir>\<analysis-symbol>\engine_telemetry\engine_payload_<as-of>.json
<results_dir>\<broker-symbol>\execution_journal\mt5_events.jsonl
```

These files are local artifacts for demo testing and troubleshooting. Review
them after a test run to see HOLD reasons, broker attempts, rejections, and data
freshness status.

## Troubleshooting

- `MetaTrader5 Python bridge is not installed`: install `MetaTrader5` in the same Python environment.
- `MT5 demo account is required`: the terminal is logged into a non-demo account or MT5 reported a non-demo trade mode.
- `unexpected MT5 account login/server`: update `.env` or log into the intended demo account.
- `MT5 terminal is not connected`: open MT5 Desktop, log in, and confirm the terminal has broker connectivity.
- `symbol must match configured MT5 symbol`: use your broker's exact symbol, such as `XAUUSD`, `XAUUSDm`, or `XAUUSD.vx`.
- No order placed because of `SKIPPED_ACTIVE_TRADE`: cancel/close the existing pending order or position first, or monitor it.
- `Data health failed. Default to HOLD.`: the bot found missing or stale required timeframe data and refused to guess.
