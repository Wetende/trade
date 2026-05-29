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
git clone git@github.com:Wetende/trade.git tradingagents
cd tradingagents
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
tradingagents mt5-demo-execute --proposal "C:\Users\you\.tradingagents\logs\XAUUSD\order_proposals\order_proposal_YYYY_MM_DD_HHMM.json"
```

Expected behavior:

- connects to MT5
- confirms the demo account guard
- refuses if an active order or position already exists for the symbol
- builds a pending `BUY_LIMIT` or `SELL_LIMIT`
- places the pending order
- records journal and state files

## 9. Monitor and Manage

Read-only snapshot:

```powershell
tradingagents mt5-demo-monitor
```

Cancel stale pending orders after the activation window:

```powershell
tradingagents mt5-demo-monitor --cancel-stale
```

Move stops to break-even when the open position qualifies:

```powershell
tradingagents mt5-demo-monitor --manage-stops
```

You can run both lifecycle actions together:

```powershell
tradingagents mt5-demo-monitor --cancel-stale --manage-stops
```

## 10. Check Audit Files

Execution events:

```text
<results_dir>\XAUUSD\execution_journal\mt5_demo_events.jsonl
```

Active pending-order state:

```text
<results_dir>\XAUUSD\execution_state\mt5_demo_state.json
```

These files are local artifacts for demo testing and troubleshooting.

## Troubleshooting

- `MetaTrader5 Python bridge is not installed`: install `MetaTrader5` in the same Python environment.
- `MT5 demo account is required`: the terminal is logged into a non-demo account or MT5 reported a non-demo trade mode.
- `unexpected MT5 account login/server`: update `.env` or log into the intended demo account.
- `MT5 terminal is not connected`: open MT5 Desktop, log in, and confirm the terminal has broker connectivity.
- `symbol must match configured MT5 symbol`: use your broker's exact symbol, such as `XAUUSD`, `XAUUSDm`, or `XAUUSD.vx`.
- No order placed because of `SKIPPED_ACTIVE_TRADE`: cancel/close the existing pending order or position first, or monitor it.
